"""DataUpdateCoordinator für Selection Fitness."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    SelectionFitnessApiError,
    SelectionFitnessAuthError,
    SelectionFitnessClient,
    extract_machines,
)
from .const import (
    CONF_PRIMARY_METRIC,
    DEFAULT_PRIMARY_METRIC,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MACHINE_METRICS,
)

_LOGGER = logging.getLogger(__name__)


class SelectionFitnessCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Holt in einem Intervall alle verfügbaren Daten."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: SelectionFitnessClient,
    ) -> None:
        minutes = entry.options.get("scan_interval_minutes")
        interval = (
            timedelta(minutes=int(minutes)) if minutes else DEFAULT_SCAN_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=interval,
        )
        self.entry = entry
        self.client = client
        # Codes, für die die Kraftmess-Historie schon importiert wurde
        self._strength_hist_done: set[str] = set()
        self._workout_stats_done = False

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            if self.client.uuid is None:
                await self.client.login()

            profile = await self.client.get_profile()
            latest_check_in = await self.client.get_latest_check_in()
            workouts = await self.client.get_workouts()
            bioage = await self.client.get_bioage()
            # Die /measurements/*/latest-metrics Endpunkte liefern für diese
            # Brand HTTP 500 und sind redundant (Körperwerte kommen aus BioAge,
            # Gewicht/Größe aus dem Profil). Daher nicht mehr abgefragt.
            measurements: dict = {}

            now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            check_in_count = await self.client.get_check_in_count(now)

            firstname = (
                (profile or {}).get("firstname")
                or self.client.profile_login.get("firstname")
                or "Selection Fitness"
            )
            machines = extract_machines(workouts)
            # Kraftmessung (fester Testwert) je Gerät holen und über den
            # Namen mergen (Kraftmess-Codes != Trainings-Codes).
            strength_by_name = await self.client.get_strength()
            matched: set[str] = set()
            for m in machines.values():
                s = strength_by_name.get(m.get("name"))
                if s:
                    m["strength"] = s
                    matched.add(m["name"])
                    if not m.get("image") and s.get("image"):
                        m["image"] = s["image"]
            # Geräte, die nur eine Kraftmessung (aber kein Training) haben
            for label, s in strength_by_name.items():
                if label in matched:
                    continue
                key = f"s_{s.get('strength_code') or label}"
                machines[key] = {
                    "name": label,
                    "source": "eGym",
                    "image": s.get("image"),
                    "sessions": [],
                    "latest": None,
                    "trend": {},
                    "strength": s,
                }
            # Historische Werte als Langzeitstatistik importieren (idempotent)
            try:
                self._import_machine_statistics(machines)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Statistik-Import übersprungen: %s", err)
            # Kraftmess-Historie je Gerät einmalig als Statistik importieren
            try:
                await self._import_strength_statistics(machines)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Kraft-Statistik-Import übersprungen: %s", err)
            # Workout-Gesamtzahl einmalig als kumulativen Verlauf importieren
            try:
                self._import_workout_statistics(workouts)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Workout-Statistik-Import übersprungen: %s", err)

            return {
                "firstname": firstname,
                "profile": profile or self.client.profile_login,
                "login": self.client.profile_login,
                "latest_check_in": latest_check_in,
                "check_in_count": check_in_count,
                "workouts": workouts,
                "workout_count": len(workouts),
                "machines": machines,
                "bioage": bioage,
                "measurements": measurements,
            }
        except SelectionFitnessAuthError as err:
            # Zugangsdaten ungültig -> Reauth auslösen
            raise UpdateFailed(f"Authentifizierung fehlgeschlagen: {err}") from err
        except SelectionFitnessApiError as err:
            raise UpdateFailed(f"API-Fehler: {err}") from err

    def _import_machine_statistics(self, machines: dict[str, Any]) -> None:
        """Importiert die historische Haupt-Metrik je Gerät als Langzeit-
        statistik. Idempotent: pro (statistic_id, Stunde) ein Bucket, erneuter
        Import überschreibt -> keine Duplikate.
        """
        # Verzögerter Import, damit die Integration ohne Recorder nicht bricht
        from homeassistant.components.recorder.statistics import (
            async_import_statistics,
        )

        metric = self.entry.options.get(CONF_PRIMARY_METRIC, DEFAULT_PRIMARY_METRIC)
        if metric not in MACHINE_METRICS:
            metric = DEFAULT_PRIMARY_METRIC
        field, unit, _dc, _icon, _label = MACHINE_METRICS[metric]

        ent_reg = er.async_get(self.hass)
        for code, m in (machines or {}).items():
            unique_id = f"{self.client.uuid}_machine_{code}"
            entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id)
            if not entity_id:
                continue  # Entity existiert noch nicht -> nächster Zyklus
            # Werte je Stundenbucket (max, falls mehrere pro Stunde)
            buckets: dict[datetime, float] = {}
            for s in m.get("sessions") or []:
                ca = s.get("completedAt")
                val = s.get(field)
                if not ca or not isinstance(val, (int, float)):
                    continue
                try:
                    dt = datetime.fromisoformat(ca.replace("Z", "+00:00"))
                except ValueError:
                    continue
                bucket = dt.replace(minute=0, second=0, microsecond=0)
                buckets[bucket] = max(float(val), buckets.get(bucket, float(val)))
            if not buckets:
                continue
            stats = [
                {"start": b, "mean": v, "min": v, "max": v}
                for b, v in sorted(buckets.items())
            ]
            metadata = {
                "has_mean": True,
                "has_sum": False,
                "name": None,
                "source": "recorder",
                "statistic_id": entity_id,
                "unit_of_measurement": unit,
            }
            async_import_statistics(self.hass, metadata, stats)

    def _import_workout_statistics(self, workouts: list[dict[str, Any]]) -> None:
        """Legt die Workout-Gesamtzahl rückwirkend als kumulativen Verlauf an
        (1, 2, … N zu den jeweiligen Trainingszeitpunkten), damit der Sensor
        nicht von 0 auf N springt. Einmalig, idempotent."""
        if self._workout_stats_done:
            return
        from homeassistant.components.recorder.statistics import (
            async_import_statistics,
        )

        ent_reg = er.async_get(self.hass)
        unique_id = f"{self.client.uuid}_workout_count"
        entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id)
        if not entity_id:
            return  # Entity noch nicht da -> nächster Zyklus
        dated: list[datetime] = []
        for w in workouts or []:
            ca = w.get("completedAt") or w.get("createdAt")
            if not ca:
                continue
            try:
                dated.append(datetime.fromisoformat(ca.replace("Z", "+00:00")))
            except ValueError:
                continue
        if not dated:
            return
        dated.sort()
        # Kumulativer Stand je Stundenbucket (letzter Index in der Stunde)
        buckets: dict[datetime, int] = {}
        for i, dt in enumerate(dated, start=1):
            bucket = dt.replace(minute=0, second=0, microsecond=0)
            buckets[bucket] = i
        stats = [
            {"start": b, "state": float(v), "sum": float(v)}
            for b, v in sorted(buckets.items())
        ]
        metadata = {
            "has_mean": False,
            "has_sum": True,
            "name": None,
            "source": "recorder",
            "statistic_id": entity_id,
            "unit_of_measurement": None,
        }
        async_import_statistics(self.hass, metadata, stats)
        self._workout_stats_done = True

    async def _import_strength_statistics(self, machines: dict[str, Any]) -> None:
        """Importiert die Kraftmess-Historie je Gerät als Langzeitstatistik.
        Einmal je Gerät (sobald dessen Strength-Entity existiert); idempotent.
        """
        from homeassistant.components.recorder.statistics import (
            async_import_statistics,
        )

        ent_reg = er.async_get(self.hass)
        for code, m in (machines or {}).items():
            strength = m.get("strength") or {}
            ex_id = strength.get("strength_code")
            if not ex_id or code in self._strength_hist_done:
                continue
            unique_id = f"{self.client.uuid}_strength_{code}"
            entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id)
            if not entity_id:
                continue  # Entity noch nicht da -> nächster Zyklus
            points = await self.client.get_strength_history(str(ex_id))
            if not points:
                # Kein Verlauf -> wenigstens den aktuellen Wert setzen
                self._strength_hist_done.add(code)
                continue
            buckets: dict[datetime, float] = {}
            for dt, val in points:
                bucket = dt.replace(minute=0, second=0, microsecond=0)
                buckets[bucket] = max(float(val), buckets.get(bucket, float(val)))
            stats = [
                {"start": b, "mean": v, "min": v, "max": v}
                for b, v in sorted(buckets.items())
            ]
            metadata = {
                "has_mean": True,
                "has_sum": False,
                "name": None,
                "source": "recorder",
                "statistic_id": entity_id,
                "unit_of_measurement": "Pkt.",
            }
            async_import_statistics(self.hass, metadata, stats)
            self._strength_hist_done.add(code)

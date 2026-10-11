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
            # Historische Werte als Langzeitstatistik importieren (idempotent)
            try:
                self._import_machine_statistics(machines)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Statistik-Import übersprungen: %s", err)

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

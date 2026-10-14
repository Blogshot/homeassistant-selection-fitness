"""DataUpdateCoordinator für Selection Fitness."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
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
    BODY_LOG_METRICS,
    CONF_PRIMARY_METRIC,
    DEFAULT_PRIMARY_METRIC,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MACHINE_METRICS,
)

_LOGGER = logging.getLogger(__name__)

# Ab HA 2026.11 verlangt async_import_statistics `mean_type` statt `has_mean`.
# Wir setzen beides, damit es auf alten und neuen Kernen ohne Warnung läuft.
# Der Enum-Ort/-Name variiert je HA-Version, daher robust auflösen.
def _resolve_mean_types() -> tuple[Any, Any]:
    import importlib

    for mod_name in (
        "homeassistant.components.recorder.models",
        "homeassistant.components.recorder.models.statistics",
        "homeassistant.components.recorder.statistics",
    ):
        try:
            mod = importlib.import_module(mod_name)
        except Exception:  # noqa: BLE001
            continue
        enum = getattr(mod, "StatisticMeanType", None)
        if enum is None:
            continue
        arithmetic = getattr(enum, "ARITHMETIC_MEAN", None) or getattr(
            enum, "ARITHMETIC", None
        )
        none_val = getattr(enum, "NONE", None)
        if arithmetic is not None and none_val is not None:
            return arithmetic, none_val
    _LOGGER.debug("StatisticMeanType not resolvable - using has_mean/has_sum only")
    return None, None


_MEAN_ARITHMETIC, _MEAN_NONE = _resolve_mean_types()


def _stat_metadata(statistic_id: str, unit: str | None, *, mean: bool) -> dict:
    """Baut Statistik-Metadaten; setzt mean_type (neu) und has_mean/has_sum
    (alt) zugleich, damit keine Deprecation-Warnung entsteht."""
    meta: dict = {
        "has_mean": mean,
        "has_sum": not mean,
        "name": None,
        "source": "recorder",
        "statistic_id": statistic_id,
        "unit_of_measurement": unit,
    }
    mean_type = _MEAN_ARITHMETIC if mean else _MEAN_NONE
    if mean_type is not None:
        meta["mean_type"] = mean_type
    # Ab HA 2026.11 Pflicht: unit_class passend zur Einheit (None = ohne
    # Umrechnung). Ältere Kerne kennen das Feld bzw. die Tabelle nicht.
    try:
        from homeassistant.components.recorder.statistics import (
            STATISTIC_UNIT_TO_UNIT_CONVERTER,
        )
    except ImportError:
        return meta
    converter = STATISTIC_UNIT_TO_UNIT_CONVERTER.get(unit)
    meta["unit_class"] = converter.UNIT_CLASS if converter else None
    return meta


_NO_STATE = object()

_UNIT_TOKENS = ("KG", "LITER", "CM2", "CM", "KJ")


def _normal_range(mtype: str, metrics: dict[str, Any]) -> tuple[Any, Any]:
    """Sucht den Normbereich zu einem Metrik-Typ im selben Messeintrag.

    Die Waage liefert z. B. FAT_FREE_MASS_KG mit FAT_FREE_MASS_LOW_KG/_TOP_KG,
    BODY_FAT_PERCENTS mit BODY_FAT_PERCENTS_LOW/_TOP und
    INTRA_CELLULAR_WATER_LITER mit INTRA_CELLULAR_WATER_LOW_KG/_TOP_KG.
    """
    base, _, unit = mtype.rpartition("_")
    if unit not in _UNIT_TOKENS:
        base = mtype
    bounds = []
    for which in ("LOW", "TOP"):
        val = metrics.get(f"{mtype}_{which}")
        if val is None:
            prefix = f"{base}_{which}_"
            val = next(
                (v for k, v in metrics.items()
                 if k.startswith(prefix) and k[len(prefix):] in _UNIT_TOKENS),
                None,
            )
        bounds.append(val)
    return bounds[0], bounds[1]


def latest_body_metrics(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Neuester Wert je Metrik-Typ (Einträge aufsteigend sortiert)."""
    result: dict[str, dict[str, Any]] = {}
    for e in entries:
        for mtype, value in e["metrics"].items():
            low, high = _normal_range(mtype, e["metrics"])
            result[mtype] = {
                "value": value,
                "createdAt": e["createdAt"],
                "source": e.get("source"),
                "sourceLabel": e.get("sourceLabel"),
                "low": low,
                "high": high,
            }
    return result


#: eGym-Analyse-Typ (bioage/history) -> Sensor-Key (unique_id-Suffix)
BIOAGE_HISTORY_MAP = {
    "TOTAL": "bio_age",
    "MUSCLE": "muscle_age",
    "CARDIO": "cardio_age",
    "METABOLIC": "metabolic_age",
    "FLEXIBILITY": "flexibility_age",
}


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
        self._bioage_hist_done = False
        # Körpermessungs-Log: einmal komplett, danach nur das laufende Jahr
        self._body_log: dict[tuple, dict[str, Any]] = {}
        self._body_log_full_done = False
        self._body_hist_done = False

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            if self.client.uuid is None:
                await self.client.login()

            profile = await self.client.get_profile()
            latest_check_in = await self.client.get_latest_check_in()
            workouts = await self.client.get_workouts()
            bioage = await self.client.get_bioage()
            # Die /measurements/*/latest-metrics Endpunkte liefern für diese
            # Brand HTTP 500. Körperwerte (u. a. Waage im Studio) kommen daher
            # aus dem Messungs-Log; BioAge/Profil haben weiterhin Vorrang.
            body_entries = await self._update_body_log()
            measurements = latest_body_metrics(body_entries)

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
                _LOGGER.debug("Statistics import skipped: %s", err)
            # Kraftmess-Historie je Gerät einmalig als Statistik importieren
            try:
                await self._import_strength_statistics(machines)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Strength statistics import skipped: %s", err)
            # Workout-Gesamtzahl einmalig als kumulativen Verlauf importieren
            try:
                self._import_workout_statistics(workouts)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Workout statistics import skipped: %s", err)
            # Körpermessungs-Historie einmalig importieren
            try:
                self._import_body_statistics(body_entries)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Body statistics import skipped: %s", err)
            # BioAge-/Fitnessalter-Historie einmalig importieren (bis ~2020)
            try:
                await self._import_bioage_statistics()
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("BioAge statistics import skipped: %s", err)

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
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except SelectionFitnessApiError as err:
            raise UpdateFailed(f"API error: {err}") from err

    async def _update_body_log(self) -> list[dict[str, Any]]:
        """Aktualisiert das Körpermessungs-Log; Fehler behalten den alten Stand."""
        try:
            entries = await self.client.get_body_measurement_log(
                full=not self._body_log_full_done
            )
        except SelectionFitnessApiError as err:
            _LOGGER.debug("Body measurements unavailable: %s", err)
        else:
            for e in entries:
                key = (e["createdAt"], tuple(sorted(e["metrics"].items())))
                self._body_log[key] = e
            self._body_log_full_done = True
        return sorted(self._body_log.values(), key=lambda e: e["created_at"])

    def _import_body_statistics(self, entries: list[dict[str, Any]]) -> None:
        """Importiert die Körpermessungen (u. a. Waage im Studio) als Langzeit-
        statistik. Einmalig, sobald mindestens eine Entity existiert; idempotent."""
        if self._body_hist_done or not entries:
            return
        from homeassistant.components.recorder.statistics import (
            async_import_statistics,
        )

        ent_reg = er.async_get(self.hass)
        found_any = False
        for key, (mtype, unit, scale, _icon, _enabled) in BODY_LOG_METRICS.items():
            unique_id = f"{self.client.uuid}_{key}"
            entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id)
            if not entity_id:
                continue
            found_any = True
            buckets: dict[datetime, float] = {}
            for e in entries:
                val = e["metrics"].get(mtype)
                if val is None:
                    continue
                bucket = e["created_at"].replace(minute=0, second=0, microsecond=0)
                buckets[bucket] = float(val) * scale
            if not buckets:
                continue
            stats = [
                {"start": b, "mean": v, "min": v, "max": v}
                for b, v in sorted(buckets.items())
            ]
            async_import_statistics(
                self.hass, _stat_metadata(entity_id, unit, mean=True), stats
            )
        if found_any:
            self._body_hist_done = True

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
        field, unit, _dc, _icon = MACHINE_METRICS[metric]

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
            entity_unit = self._entity_unit(entity_id, unit)
            if entity_unit is _NO_STATE:
                continue  # unit not known yet -> next cycle
            stats = [
                {"start": b, "mean": v, "min": v, "max": v}
                for b, v in sorted(buckets.items())
            ]
            metadata = _stat_metadata(entity_id, entity_unit, mean=True)
            async_import_statistics(self.hass, metadata, stats)

    def _entity_unit(self, entity_id: str, fallback: str | None) -> Any:
        """Unit of the entity as shown in HA.

        Some units come from the translations (e.g. strength points) and thus
        depend on the system language; imported statistics must use exactly
        that unit. Returns _NO_STATE if the entity has no state yet.
        """
        if fallback is not None:
            return fallback
        state = self.hass.states.get(entity_id)
        if state is None:
            return _NO_STATE
        return state.attributes.get("unit_of_measurement")

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
        metadata = _stat_metadata(entity_id, None, mean=False)
        async_import_statistics(self.hass, metadata, stats)
        self._workout_stats_done = True

    async def _import_bioage_statistics(self) -> None:
        """Importiert die Historie der Fitness-Alter (Körper-, Kraft-, Cardio-,
        Stoffwechsel-, Flexibilitätsalter) als Langzeitstatistik, zurück bis zur
        ersten Messung. Einmalig (sobald die Entities existieren); idempotent."""
        if self._bioage_hist_done:
            return
        from homeassistant.components.recorder.statistics import (
            async_import_statistics,
        )

        ent_reg = er.async_get(self.hass)
        # Zuordnung analysisType -> (entity_id) vorab prüfen
        targets: dict[str, str] = {}
        for mtype, key in BIOAGE_HISTORY_MAP.items():
            unique_id = f"{self.client.uuid}_{key}"
            entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id)
            if entity_id:
                targets[mtype] = entity_id
        if not targets:
            return  # Entities noch nicht da -> nächster Zyklus

        history = await self.client.get_bioage_history()
        if not history:
            # Kein Verlauf abrufbar -> nicht erneut versuchen
            self._bioage_hist_done = True
            return
        imported_any = False
        for mtype, entity_id in targets.items():
            points = history.get(mtype)
            if not points:
                continue
            buckets: dict[datetime, float] = {}
            for dt, val in points:
                bucket = dt.replace(minute=0, second=0, microsecond=0)
                buckets[bucket] = float(val)
            if not buckets:
                continue
            stats = [
                {"start": b, "mean": v, "min": v, "max": v}
                for b, v in sorted(buckets.items())
            ]
            metadata = _stat_metadata(entity_id, "a", mean=True)
            async_import_statistics(self.hass, metadata, stats)
            imported_any = True
        if imported_any:
            self._bioage_hist_done = True

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
            entity_unit = self._entity_unit(entity_id, None)
            if entity_unit is _NO_STATE:
                continue  # unit not known yet -> next cycle
            metadata = _stat_metadata(entity_id, entity_unit, mean=True)
            async_import_statistics(self.hass, metadata, stats)
            self._strength_hist_done.add(code)

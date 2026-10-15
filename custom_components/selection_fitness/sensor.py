"""Sensor-Entities für Selection Fitness."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import compute_trend
from .const import (
    BODY_LOG_METRICS,
    CONF_PRIMARY_METRIC,
    DEFAULT_PRIMARY_METRIC,
    DOMAIN,
    MACHINE_METRICS,
)
from .coordinator import SelectionFitnessCoordinator


def _device_name(data: dict[str, Any]) -> str:
    fn = (data or {}).get("firstname") or "Selection Fitness"
    return f"Selection Fitness ({fn})" if fn != "Selection Fitness" else "Selection Fitness"


def _parse_dt(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    txt = value.replace("Z", "+00:00")
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(txt)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    # HA verlangt bei TIMESTAMP-Sensoren zeitzonenbewusste Werte
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@dataclass(frozen=True, kw_only=True)
class SFSensorDescription(SensorEntityDescription):
    """Beschreibung inkl. Wert-Extraktor."""

    value_fn: Callable[[dict[str, Any]], Any]
    available_fn: Callable[[dict[str, Any]], bool] = lambda data: True
    # Metrik-Typ im Körpermessungs-Log (für Attribute wie Normbereich)
    body_metric: str | None = None
    scale: float = 1.0


def _metric(data: dict[str, Any], mtype: str) -> Any:
    m = data.get("measurements", {}).get(mtype)
    if m is None:
        return None
    return m.get("value")


def _has_metric(data: dict[str, Any], *mtypes: str) -> bool:
    measurements = data.get("measurements", {})
    return any(t in measurements for t in mtypes)


def _scaled(value: Any, scale: float) -> Any:
    if not isinstance(value, (int, float)):
        return None
    return round(float(value) * scale, 0 if scale != 1.0 else 2)


_UNIT_DEVICE_CLASS = {
    "kg": SensorDeviceClass.WEIGHT,
    # VOLUME erlaubt nur total/total_increasing, VOLUME_STORAGE auch measurement
    "L": SensorDeviceClass.VOLUME_STORAGE,
    "cm": SensorDeviceClass.DISTANCE,
}


def _body_log_descriptions() -> tuple[SFSensorDescription, ...]:
    """Sensoren für Werte aus dem Körpermessungs-Log (u. a. Studio-Waage)."""
    descs = []
    for key, (mtype, unit, scale, icon, enabled) in BODY_LOG_METRICS.items():
        descs.append(
            SFSensorDescription(
                key=key,
                translation_key=key,
                native_unit_of_measurement=unit,
                device_class=_UNIT_DEVICE_CLASS.get(unit),
                state_class=SensorStateClass.MEASUREMENT,
                icon=icon,
                entity_registry_enabled_default=enabled,
                body_metric=mtype,
                scale=scale,
                value_fn=lambda d, t=mtype, f=scale: _scaled(_metric(d, t), f),
                available_fn=lambda d, t=mtype: _has_metric(d, t),
            )
        )
    return tuple(descs)


def _profile(data: dict[str, Any], key: str) -> Any:
    val = data.get("profile", {}).get(key)
    return val if val not in ("", None) else None


def _bio(data: dict[str, Any], key: str) -> Any:
    return data.get("bioage", {}).get(key)


def _bio_or_metric(data: dict[str, Any], bio_key: str, *metric_types: str) -> Any:
    """BioAge-Wert bevorzugen (zuverlässig), sonst Messwert-Endpunkt."""
    v = _bio(data, bio_key)
    if v is not None:
        return v
    for mt in metric_types:
        m = _metric(data, mt)
        if m is not None:
            return m
    return None


def _profile_weight(data: dict[str, Any]) -> Any:
    """Gewicht bevorzugt aus dem Profil (zuverlässig), sonst Messwert."""
    w = _profile(data, "weight")
    if isinstance(w, (int, float)) and w > 0:
        return round(float(w), 1)
    return _metric(data, "weight")


def _profile_height(data: dict[str, Any]) -> Any:
    h = _profile(data, "height")
    if isinstance(h, (int, float)) and h > 0:
        return round(float(h), 1)
    return _metric(data, "height")


def _workouts(data: dict[str, Any]) -> list[dict[str, Any]]:
    w = data.get("workouts")
    return w if isinstance(w, list) else []


def _last_workout(data: dict[str, Any]) -> dict[str, Any] | None:
    workouts = _workouts(data)
    if not workouts:
        return None
    # jüngstes nach completedAt
    def key(w: dict[str, Any]) -> str:
        return w.get("completedAt") or w.get("createdAt") or ""

    return max(workouts, key=key)


SENSORS: tuple[SFSensorDescription, ...] = (
    # --- Körpermesswerte -------------------------------------------------
    SFSensorDescription(
        key="weight",
        translation_key="weight",
        native_unit_of_measurement="kg",
        device_class=SensorDeviceClass.WEIGHT,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:scale-bathroom",
        value_fn=_profile_weight,
        available_fn=lambda d: _profile_weight(d) is not None,
    ),
    SFSensorDescription(
        key="body_fat",
        translation_key="body_fat",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:percent",
        value_fn=lambda d: _bio_or_metric(d, "body_fat", "bodyFat"),
        available_fn=lambda d: _bio_or_metric(d, "body_fat", "bodyFat") is not None,
    ),
    SFSensorDescription(
        key="bmi",
        translation_key="bmi",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:human",
        value_fn=lambda d: _bio_or_metric(d, "bmi", "BMI", "bmi"),
        available_fn=lambda d: _bio_or_metric(d, "bmi", "BMI", "bmi") is not None,
    ),
    SFSensorDescription(
        key="waist_hip_ratio",
        translation_key="waist_hip_ratio",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:tape-measure",
        value_fn=lambda d: _bio(d, "waist_hip_ratio"),
        available_fn=lambda d: _bio(d, "waist_hip_ratio") is not None,
    ),
    # --- eGym BioAge / Fitness-Alter ------------------------------------
    SFSensorDescription(
        key="bio_age",
        translation_key="bio_age",
        native_unit_of_measurement="a",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cake-variant",
        value_fn=lambda d: _bio(d, "bio_age"),
        available_fn=lambda d: _bio(d, "bio_age") is not None,
    ),
    SFSensorDescription(
        key="muscle_age",
        translation_key="muscle_age",
        native_unit_of_measurement="a",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:arm-flex",
        value_fn=lambda d: _bio(d, "muscle_age"),
        available_fn=lambda d: _bio(d, "muscle_age") is not None,
    ),
    SFSensorDescription(
        key="upper_body_age",
        translation_key="upper_body_age",
        native_unit_of_measurement="a",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:arm-flex",
        value_fn=lambda d: _bio(d, "upper_body_age"),
        available_fn=lambda d: _bio(d, "upper_body_age") is not None,
    ),
    SFSensorDescription(
        key="core_age",
        translation_key="core_age",
        native_unit_of_measurement="a",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:human",
        value_fn=lambda d: _bio(d, "core_age"),
        available_fn=lambda d: _bio(d, "core_age") is not None,
    ),
    SFSensorDescription(
        key="lower_body_age",
        translation_key="lower_body_age",
        native_unit_of_measurement="a",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:human-handsdown",
        value_fn=lambda d: _bio(d, "lower_body_age"),
        available_fn=lambda d: _bio(d, "lower_body_age") is not None,
    ),
    SFSensorDescription(
        key="upper_body_balance",
        translation_key="upper_body_balance",
        icon="mdi:scale-balance",
        value_fn=lambda d: _bio(d, "upper_body_state"),
        available_fn=lambda d: _bio(d, "upper_body_state") is not None,
    ),
    SFSensorDescription(
        key="core_balance",
        translation_key="core_balance",
        icon="mdi:scale-balance",
        value_fn=lambda d: _bio(d, "core_body_state"),
        available_fn=lambda d: _bio(d, "core_body_state") is not None,
    ),
    SFSensorDescription(
        key="lower_body_balance",
        translation_key="lower_body_balance",
        icon="mdi:scale-balance",
        value_fn=lambda d: _bio(d, "lower_body_state"),
        available_fn=lambda d: _bio(d, "lower_body_state") is not None,
    ),
    SFSensorDescription(
        key="cardio_age",
        translation_key="cardio_age",
        native_unit_of_measurement="a",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heart-pulse",
        value_fn=lambda d: _bio(d, "cardio_age"),
        available_fn=lambda d: _bio(d, "cardio_age") is not None,
    ),
    SFSensorDescription(
        key="flexibility_age",
        translation_key="flexibility_age",
        native_unit_of_measurement="a",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:yoga",
        value_fn=lambda d: _bio(d, "flexibility_age"),
        available_fn=lambda d: _bio(d, "flexibility_age") is not None,
    ),
    SFSensorDescription(
        key="metabolic_age",
        translation_key="metabolic_age",
        native_unit_of_measurement="a",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:fire",
        value_fn=lambda d: _bio(d, "metabolic_age"),
        available_fn=lambda d: _bio(d, "metabolic_age") is not None,
    ),
    SFSensorDescription(
        key="height",
        translation_key="height",
        native_unit_of_measurement="cm",
        device_class=SensorDeviceClass.DISTANCE,
        icon="mdi:human-male-height",
        value_fn=_profile_height,
        available_fn=lambda d: _profile_height(d) is not None,
    ),
    SFSensorDescription(
        key="gender",
        translation_key="gender",
        icon="mdi:gender-male-female",
        value_fn=lambda d: _profile(d, "gender"),
        available_fn=lambda d: _profile(d, "gender") is not None,
    ),
    SFSensorDescription(
        key="measurement_unit",
        translation_key="measurement_unit",
        icon="mdi:ruler",
        value_fn=lambda d: _profile(d, "measurementUnit"),
        available_fn=lambda d: _profile(d, "measurementUnit") is not None,
    ),
    # --- Cardio / Vitalwerte --------------------------------------------
    SFSensorDescription(
        key="vo2max",
        translation_key="vo2max",
        native_unit_of_measurement="mL/kg/min",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:lungs",
        value_fn=lambda d: _bio_or_metric(d, "vo2max", "vo2Max"),
        available_fn=lambda d: _bio_or_metric(d, "vo2max", "vo2Max") is not None,
    ),
    SFSensorDescription(
        key="resting_heart_rate",
        translation_key="resting_heart_rate",
        native_unit_of_measurement="bpm",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heart-pulse",
        value_fn=lambda d: _bio_or_metric(d, "resting_heart_rate", "restingHeartRate", "bpm"),
        available_fn=lambda d: _bio_or_metric(d, "resting_heart_rate", "restingHeartRate", "bpm") is not None,
    ),
    SFSensorDescription(
        key="blood_pressure_systolic",
        translation_key="blood_pressure_systolic",
        native_unit_of_measurement="mmHg",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heart",
        value_fn=lambda d: _bio_or_metric(d, "systolic", "systolic"),
        available_fn=lambda d: _bio_or_metric(d, "systolic", "systolic") is not None,
    ),
    SFSensorDescription(
        key="blood_pressure_diastolic",
        translation_key="blood_pressure_diastolic",
        native_unit_of_measurement="mmHg",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heart",
        value_fn=lambda d: _bio_or_metric(d, "diastolic", "diastolic"),
        available_fn=lambda d: _bio_or_metric(d, "diastolic", "diastolic") is not None,
    ),
    # --- Training / Mitgliedschaft --------------------------------------
    SFSensorDescription(
        key="workout_count",
        translation_key="workout_count",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:dumbbell",
        value_fn=lambda d: len(_workouts(d)),
        available_fn=lambda d: bool(_workouts(d)),
    ),
    SFSensorDescription(
        key="last_workout",
        translation_key="last_workout",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:calendar-check",
        value_fn=lambda d: _parse_dt((_last_workout(d) or {}).get("completedAt")),
        available_fn=lambda d: _last_workout(d) is not None,
    ),
    SFSensorDescription(
        key="last_workout_plan",
        translation_key="last_workout_plan",
        icon="mdi:clipboard-text",
        value_fn=lambda d: (_last_workout(d) or {}).get("workoutPlanLabel"),
        available_fn=lambda d: bool((_last_workout(d) or {}).get("workoutPlanLabel")),
    ),
    SFSensorDescription(
        key="last_workout_exercises",
        translation_key="last_workout_exercises",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:format-list-numbered",
        value_fn=lambda d: len((_last_workout(d) or {}).get("exercises") or []),
        available_fn=lambda d: _last_workout(d) is not None,
    ),
    SFSensorDescription(
        key="check_in_count",
        translation_key="check_in_count",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:door",
        value_fn=lambda d: d.get("check_in_count"),
        available_fn=lambda d: d.get("check_in_count") is not None,
    ),
    SFSensorDescription(
        key="last_check_in",
        translation_key="last_check_in",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:calendar-check",
        value_fn=lambda d: _parse_dt(
            (d.get("latest_check_in") or {}).get("checkInDate")
        ),
        available_fn=lambda d: bool(d.get("latest_check_in")),
    ),
    SFSensorDescription(
        key="last_club",
        translation_key="last_club",
        icon="mdi:map-marker",
        value_fn=lambda d: (d.get("latest_check_in") or {}).get("gymLocationName"),
        available_fn=lambda d: bool(
            (d.get("latest_check_in") or {}).get("gymLocationName")
        ),
    ),
    SFSensorDescription(
        key="membership_type",
        translation_key="membership_type",
        icon="mdi:card-account-details",
        value_fn=lambda d: d.get("login", {}).get("membershipType")
        or d.get("profile", {}).get("membershipType"),
        available_fn=lambda d: bool(
            d.get("login", {}).get("membershipType")
            or d.get("profile", {}).get("membershipType")
        ),
    ),
    SFSensorDescription(
        key="home_club",
        translation_key="home_club",
        icon="mdi:home",
        value_fn=lambda d: d.get("login", {}).get("homeClubChainName")
        or d.get("profile", {}).get("homeClubName"),
        available_fn=lambda d: bool(
            d.get("login", {}).get("homeClubChainName")
            or d.get("profile", {}).get("homeClubName")
        ),
    ),
) + _body_log_descriptions()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Richte die Sensoren ein."""
    coordinator: SelectionFitnessCoordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data or {}

    entities: list[SensorEntity] = [
        SelectionFitnessSensor(coordinator, desc)
        for desc in SENSORS
        if desc.available_fn(data)
    ]
    # Pro-Gerät-Sensoren (eGym-Maschinen) dynamisch aus der Historie
    metric = coordinator.entry.options.get(CONF_PRIMARY_METRIC, DEFAULT_PRIMARY_METRIC)
    if metric not in MACHINE_METRICS:
        metric = DEFAULT_PRIMARY_METRIC
    for code, machine in (data.get("machines") or {}).items():
        # Trainings-Sensor nur, wenn es Trainings-Sessions gibt
        if machine.get("sessions"):
            entities.append(
                SelectionFitnessMachineSensor(coordinator, code, machine["name"], metric)
            )
        # Eigener Kraftmess-Sensor, wenn eine Kraftmessung vorliegt
        if machine.get("strength"):
            entities.append(
                SelectionFitnessStrengthSensor(coordinator, code, machine["name"])
            )

    async_add_entities(entities)


def _machines_device_info(coordinator: SelectionFitnessCoordinator) -> DeviceInfo:
    """Shared device for all eGym machines of one person (name translated)."""
    fn = (coordinator.data or {}).get("firstname") or ""
    named = bool(fn) and fn != "Selection Fitness"
    return DeviceInfo(
        identifiers={(DOMAIN, f"{coordinator.client.uuid}_machines")},
        translation_key="machines_person" if named else "machines",
        translation_placeholders={"person": fn} if named else None,
        manufacturer="eGym",
        model="Fitness Machines",
    )


class SelectionFitnessStrengthSensor(
    CoordinatorEntity[SelectionFitnessCoordinator], SensorEntity
):
    """eGym-Kraftmessung je Gerät (fester Testwert) mit Verlauf/Historie.

    Ohne state_class (siehe Geräte-Sensor): die Kraftmessung erfolgt nur beim
    Test, nicht laufend. Die Verlaufshistorie kommt als externe Statistik.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "machine_strength_test"
    _attr_native_unit_of_measurement = "pts"
    _attr_icon = "mdi:arm-flex"

    def __init__(
        self,
        coordinator: SelectionFitnessCoordinator,
        code: str,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self._code = code
        self._attr_translation_placeholders = {"machine": name}
        self._attr_unique_id = f"{coordinator.client.uuid}_strength_{code}"
        self._attr_device_info = _machines_device_info(coordinator)
        m = ((coordinator.data or {}).get("machines") or {}).get(code) or {}
        if m.get("image"):
            self._attr_entity_picture = m["image"]

    def _strength(self) -> dict[str, Any]:
        m = (self.coordinator.data or {}).get("machines", {}).get(self._code) or {}
        return m.get("strength") or {}

    @property
    def native_value(self) -> Any:
        return self._strength().get("value")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        s = self._strength()
        if not s:
            return None
        return {
            "progress": s.get("progress"),
            "change_pct": s.get("change_pct"),
            "measured_at": s.get("created_at"),
            "body_region": s.get("body_region"),
            "exercise_code": s.get("strength_code"),
        }


class SelectionFitnessMachineSensor(
    CoordinatorEntity[SelectionFitnessCoordinator], SensorEntity
):
    """Ein eGym-Gerät: Zustand = wählbare Haupt-Metrik, alle Werte als Attribute.

    Bewusst OHNE state_class: Trainings sind sporadische Ereignisse, kein
    kontinuierlicher Messwert. Sonst würde der Recorder den letzten Wert
    stündlich rund um die Uhr als Statistik fortschreiben (ein Punkt alle x
    Minuten statt pro Training). Die echte Pro-Training-Historie liefert der
    Coordinator als eigene externe Langzeitstatistik.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SelectionFitnessCoordinator,
        code: str,
        name: str,
        metric: str,
    ) -> None:
        super().__init__(coordinator)
        self._code = code
        self._metric = metric
        field, unit, dev_class, icon = MACHINE_METRICS[metric]
        self._field = field
        self._attr_translation_key = f"machine_{metric}"
        self._attr_translation_placeholders = {"machine": name}
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        if dev_class == "weight":
            self._attr_device_class = SensorDeviceClass.WEIGHT
        self._attr_unique_id = f"{coordinator.client.uuid}_machine_{code}"
        self._attr_device_info = _machines_device_info(coordinator)
        m = ((coordinator.data or {}).get("machines") or {}).get(code) or {}
        if m.get("image"):
            self._attr_entity_picture = m["image"]

    def _machine(self) -> dict[str, Any] | None:
        return (self.coordinator.data or {}).get("machines", {}).get(self._code)

    @property
    def native_value(self) -> Any:
        m = self._machine() or {}
        if self._field == "strength":
            return (m.get("strength") or {}).get("value")
        return (m.get("latest") or {}).get(self._field)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        m = self._machine()
        if not m:
            return None
        latest = m.get("latest") or {}
        strength = m.get("strength") or {}
        trend = compute_trend(m.get("sessions") or [], self._field) if self._field != "strength" else {}
        return {
            "weight_kg": latest.get("weight"),
            "reps": latest.get("reps"),
            "sets": latest.get("sets"),
            "calories": latest.get("calories"),
            "activity_points": latest.get("activity_points"),
            "training_method": latest.get("training_method"),
            "last_trained": latest.get("completedAt"),
            "session_count": len(m.get("sessions") or []),
            # Kraftmessung (fester Testwert, unabhängig vom eingestellten Gewicht)
            "strength_value": strength.get("value"),
            "strength_measured_at": strength.get("created_at"),
            "strength_progress": strength.get("progress"),
            "strength_change_pct": strength.get("change_pct"),
            "trend": trend.get("direction"),
            "trend_per_month": trend.get("slope_per_month"),
            "projected_next": trend.get("projected_next"),
            "primary_metric": self._metric,
            "source": m.get("source"),
            "exercise_code": self._code,
            "entity_picture": m.get("image"),
        }


class SelectionFitnessSensor(
    CoordinatorEntity[SelectionFitnessCoordinator], SensorEntity
):
    """Ein einzelner Messwert-Sensor."""

    entity_description: SFSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SelectionFitnessCoordinator,
        description: SFSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.client.uuid}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.client.uuid or coordinator.entry.entry_id)},
            name=_device_name(coordinator.data or {}),
            manufacturer="Netpulse / eGym",
            model="Selection Fitness Account",
        )

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data or {})

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Zeige Quelle und Messzeitpunkt bei Körpermesswerten."""
        key = self.entity_description.key
        measurements = (self.coordinator.data or {}).get("measurements", {})
        body_metric = self.entity_description.body_metric
        if body_metric:
            m = measurements.get(body_metric)
            if not m:
                return None
            scale = self.entity_description.scale
            attrs = {
                "measured_at": m.get("createdAt"),
                "source": m.get("sourceLabel") or m.get("source"),
            }
            if m.get("low") is not None and m.get("high") is not None:
                attrs["normal_low"] = _scaled(m["low"], scale)
                attrs["normal_high"] = _scaled(m["high"], scale)
            return attrs
        # Mapping Sensor-Key -> Metrik-Typ für Attribute
        type_map = {
            "weight": "weight",
            "body_fat": "bodyFat",
            "bmi": "BMI",
            "height": "height",
            "vo2max": "vo2Max",
            "resting_heart_rate": "restingHeartRate",
            "blood_pressure_systolic": "systolic",
            "blood_pressure_diastolic": "diastolic",
        }
        mtype = type_map.get(key)
        if mtype and mtype in measurements:
            m = measurements[mtype]
            return {
                "measured_at": m.get("createdAt"),
                "source": m.get("sourceLabel") or m.get("source"),
            }
        return None

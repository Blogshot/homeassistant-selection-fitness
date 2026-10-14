"""Konstanten für die Selection Fitness Integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "selection_fitness"

# --- API-Konfiguration (aus der App rekonstruiert) -------------------------
# Haupt-Backend dieser Brand (sicher, aus den App-Ressourcen):
DEFAULT_BASE_URL = "https://selectionfitness.netpulse.com"
# eGym Mobile-API-Host für Körpermesswerte, BioAge, Kraft, Flexibilität.
# Exakt der Wert aus der App-Ressource `mobile_api_url` (Standalone-Brand-App
# nutzt diesen Default direkt). Konfigurierbar, falls er je abweicht.
DEFAULT_MOBILE_API_URL = "https://mobile-api.int.api.egym.com"

# Pflicht-Header der App
API_VERSION = "1.5"
APP_VERSION = "1.7"
APP_VERSION_CODE = "119"
BRAND_NAME = "SelectionFitness"

# Config-Entry Keys
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_BASE_URL = "base_url"
CONF_MOBILE_API_URL = "mobile_api_url"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_PRIMARY_METRIC = "primary_metric"

DEFAULT_SCAN_INTERVAL = timedelta(minutes=30)
DEFAULT_PRIMARY_METRIC = "weight"

# Selectable primary metric per machine (configurable per config entry).
# key -> (session field, unit, device_class|None, icon)
# unit None: the unit comes from the translations (entity.sensor.machine_<key>),
# so it is shown in the user's language.
MACHINE_METRICS: dict[str, tuple] = {
    "weight": ("weight", "kg", "weight", "mdi:dumbbell"),
    "strength": ("strength", None, None, "mdi:arm-flex"),
    "calories": ("calories", "kcal", None, "mdi:fire"),
    "activity_points": ("activity_points", None, None, "mdi:star-four-points"),
    "reps": ("reps", None, None, "mdi:counter"),
}

# Messwert-Typen, die bei den latest-metrics Endpunkten angefragt werden.
# (Aus MeasurementTypeKt der App.)
BODY_METRIC_TYPES = [
    "weight",
    "bodyFat",
    "BMI",
    "bmi",
    "height",
    "waist",
    "hip",
    "muscleMass",
    "leanBodyMass",
    "visceralFat",
    "basalMetabolicRate",
]
CARDIO_METRIC_TYPES = [
    "vo2Max",
    "bpm",
    "restingHeartRate",
    "systolic",
    "diastolic",
]

# Körpermessungen aus dem Messungs-Log (/measurements/.../body-measurements),
# u. a. von der Body-Analyse-Waage im Studio (Quelle "fithub").
# key -> (Metrik-Typ, Einheit, Skalierung, Icon, standardmäßig aktiv)
BODY_LOG_METRICS: dict[str, tuple[str, str | None, float, str, bool]] = {
    "muscle_mass": ("SKELETAL_MUSCLE_MASS_KG", "kg", 1.0, "mdi:arm-flex", True),
    "lean_body_mass": ("FAT_FREE_MASS_KG", "kg", 1.0, "mdi:weight-lifter", True),
    "body_fat_mass": ("BODY_FAT_MASS_KG", "kg", 1.0, "mdi:scale-bathroom", True),
    "visceral_fat": ("VISCERAL_FAT_LEVEL_CM2", None, 1.0, "mdi:stomach", True),
    "visceral_fat_area": ("VISCERAL_FAT_AREA_CM2", "cm²", 1.0, "mdi:stomach", True),
    # Waage liefert kJ, Sensor zeigt kcal
    "bmr": ("BASAL_METABOLIC_RATE_KJ", "kcal", 1 / 4.184, "mdi:fire", True),
    "body_water": ("BODY_WATER_LITER", "L", 1.0, "mdi:water", True),
    "intracellular_water": ("INTRA_CELLULAR_WATER_LITER", "L", 1.0, "mdi:water-outline", True),
    "extracellular_water": ("EXTRA_CELLULAR_WATER_LITER", "L", 1.0, "mdi:water-outline", True),
    "ecw_tbw_ratio": ("ECW_TBW_PERCENT", "%", 1.0, "mdi:water-percent", True),
    "phase_angle": ("BODY_PHASE_ANGLE", "°", 1.0, "mdi:sine-wave", True),
    "waist": ("WAIST_CM", "cm", 1.0, "mdi:tape-measure", True),
    "hip": ("HIP_CM", "cm", 1.0, "mdi:tape-measure", True),
    "fat_left_arm": ("SEGMENTAL_FAT_LEFT_ARM_KG", "kg", 1.0, "mdi:arm-flex-outline", False),
    "fat_right_arm": ("SEGMENTAL_FAT_RIGHT_ARM_KG", "kg", 1.0, "mdi:arm-flex-outline", False),
    "fat_left_leg": ("SEGMENTAL_FAT_LEFT_LEG_KG", "kg", 1.0, "mdi:shoe-print", False),
    "fat_right_leg": ("SEGMENTAL_FAT_RIGHT_LEG_KG", "kg", 1.0, "mdi:shoe-print", False),
    "fat_trunk": ("SEGMENTAL_FAT_TRUNK_KG", "kg", 1.0, "mdi:human-handsdown", False),
    "lean_left_arm": ("SEGMENTAL_LEAN_LEFT_ARM_KG", "kg", 1.0, "mdi:arm-flex", False),
    "lean_right_arm": ("SEGMENTAL_LEAN_RIGHT_ARM_KG", "kg", 1.0, "mdi:arm-flex", False),
    "lean_left_leg": ("SEGMENTAL_LEAN_LEFT_LEG_KG", "kg", 1.0, "mdi:shoe-print", False),
    "lean_right_leg": ("SEGMENTAL_LEAN_RIGHT_LEG_KG", "kg", 1.0, "mdi:shoe-print", False),
    "lean_trunk": ("SEGMENTAL_LEAN_TRUNK_KG", "kg", 1.0, "mdi:human-handsdown", False),
}

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

# Wählbare Haupt-Metrik je Gerät (pro Person/Config-Entry einstellbar).
# key -> (session-Feld, Einheit, device_class|None, icon, Anzeigename)
MACHINE_METRICS: dict[str, tuple] = {
    "weight": ("weight", "kg", "weight", "mdi:dumbbell", "Gestemmtes Gewicht"),
    "calories": ("calories", "kcal", None, "mdi:fire", "Kalorien"),
    "activity_points": ("activity_points", "Punkte", None, "mdi:star-four-points", "Aktivitätspunkte"),
    "reps": ("reps", "Wdh.", None, "mdi:counter", "Wiederholungen"),
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

"""Services zum Schreiben von Messwerten ins Selection-/eGym-Konto.

Nutzt denselben Endpunkt wie der Health-Connect-Sync der App, damit der
Messzeitpunkt (auch rückwirkend) erhalten bleibt. Geschriebene Einträge
lassen sich über die API nicht wieder löschen.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .api import SelectionFitnessApiError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_ADD_BODY = "add_body_measurement"
SERVICE_ADD_CARDIO = "add_cardio_measurement"

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_MEASURED_AT = "measured_at"
ATTR_WEIGHT = "weight"
ATTR_BODY_FAT = "body_fat"
ATTR_HEIGHT = "height"
ATTR_RESTING_HEART_RATE = "resting_heart_rate"
ATTR_SYSTOLIC = "systolic"
ATTR_DIASTOLIC = "diastolic"
ATTR_VO2MAX = "vo2max"

# Wertebereiche wie in der App (AnalysisNewValue)
_BASE_SCHEMA = {
    vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    vol.Optional(ATTR_MEASURED_AT): cv.datetime,
}

BODY_SCHEMA = vol.Schema(
    {
        **_BASE_SCHEMA,
        vol.Optional(ATTR_WEIGHT): vol.All(vol.Coerce(float), vol.Range(min=30, max=300)),
        vol.Optional(ATTR_BODY_FAT): vol.All(vol.Coerce(float), vol.Range(min=4, max=70)),
        vol.Optional(ATTR_HEIGHT): vol.All(vol.Coerce(float), vol.Range(min=120, max=250)),
    }
)

CARDIO_SCHEMA = vol.Schema(
    {
        **_BASE_SCHEMA,
        vol.Optional(ATTR_RESTING_HEART_RATE): vol.All(vol.Coerce(int), vol.Range(min=30, max=230)),
        vol.Optional(ATTR_SYSTOLIC): vol.All(vol.Coerce(int), vol.Range(min=30, max=200)),
        vol.Optional(ATTR_DIASTOLIC): vol.All(vol.Coerce(int), vol.Range(min=30, max=200)),
        vol.Optional(ATTR_VO2MAX): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
    }
)


def _get_coordinator(hass: HomeAssistant, call: ServiceCall):
    coordinators: dict[str, Any] = hass.data.get(DOMAIN, {})
    entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
    if entry_id:
        coordinator = coordinators.get(entry_id)
        if coordinator is None:
            raise ServiceValidationError(
                f"Kein geladener Selection-Fitness-Eintrag mit ID {entry_id}"
            )
        return coordinator
    if len(coordinators) == 1:
        return next(iter(coordinators.values()))
    if not coordinators:
        raise ServiceValidationError("Kein Selection-Fitness-Konto eingerichtet")
    raise ServiceValidationError(
        "Mehrere Selection-Fitness-Konten eingerichtet – bitte config_entry_id angeben"
    )


def _measured_at(call: ServiceCall):
    measured_at = call.data.get(ATTR_MEASURED_AT) or dt_util.now()
    if measured_at.tzinfo is None:
        measured_at = measured_at.replace(tzinfo=dt_util.get_default_time_zone())
    if measured_at > dt_util.now():
        raise ServiceValidationError("measured_at darf nicht in der Zukunft liegen")
    return measured_at


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Registriert die Schreib-Services."""

    async def _add_body(call: ServiceCall) -> None:
        values = {
            k: call.data.get(k) for k in (ATTR_WEIGHT, ATTR_BODY_FAT, ATTR_HEIGHT)
        }
        if values[ATTR_WEIGHT] is None and values[ATTR_BODY_FAT] is None:
            raise ServiceValidationError("weight oder body_fat muss angegeben werden")
        coordinator = _get_coordinator(hass, call)
        if values[ATTR_HEIGHT] is None:
            # Ohne Größe ergänzt der Server selbst die Profilgröße – explizit
            # mitsenden, damit der BMI nachvollziehbar aus bekannten Werten entsteht.
            height = ((coordinator.data or {}).get("profile") or {}).get("height")
            if isinstance(height, (int, float)) and height > 0:
                values[ATTR_HEIGHT] = float(height)
        try:
            await coordinator.client.post_body_measurement(
                measured_at=_measured_at(call),
                tz_name=hass.config.time_zone,
                **values,
            )
        except SelectionFitnessApiError as err:
            raise HomeAssistantError(f"Messwert konnte nicht gesendet werden: {err}") from err
        await coordinator.async_request_refresh()

    async def _add_cardio(call: ServiceCall) -> None:
        values = {
            k: call.data.get(k)
            for k in (ATTR_RESTING_HEART_RATE, ATTR_SYSTOLIC, ATTR_DIASTOLIC, ATTR_VO2MAX)
        }
        if all(v is None for v in values.values()):
            raise ServiceValidationError("Mindestens ein Messwert muss angegeben werden")
        if (values[ATTR_SYSTOLIC] is None) != (values[ATTR_DIASTOLIC] is None):
            raise ServiceValidationError("Blutdruck braucht systolic und diastolic")
        coordinator = _get_coordinator(hass, call)
        try:
            await coordinator.client.post_cardio_measurement(
                measured_at=_measured_at(call),
                tz_name=hass.config.time_zone,
                **values,
            )
        except SelectionFitnessApiError as err:
            raise HomeAssistantError(f"Messwert konnte nicht gesendet werden: {err}") from err
        await coordinator.async_request_refresh()

    hass.services.async_register(DOMAIN, SERVICE_ADD_BODY, _add_body, schema=BODY_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_ADD_CARDIO, _add_cardio, schema=CARDIO_SCHEMA)

"""Services zum Schreiben von Messwerten ins Selection-/eGym-Konto.

Nutzt denselben Endpunkt wie der Health-Connect-Sync der App, damit der
Messzeitpunkt (auch rückwirkend) erhalten bleibt. Geschriebene Einträge
lassen sich über die API nicht wieder löschen.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.translation import async_get_translations
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
ATTR_FORCE_BACKDATE = "force_backdate"
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
        vol.Optional(ATTR_FORCE_BACKDATE, default=False): cv.boolean,
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
                translation_domain=DOMAIN,
                translation_key="entry_not_found",
                translation_placeholders={"entry_id": entry_id},
            )
        return coordinator
    if len(coordinators) == 1:
        return next(iter(coordinators.values()))
    if not coordinators:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_account"
        )
    raise ServiceValidationError(
        translation_domain=DOMAIN, translation_key="multiple_accounts"
    )


def _measured_at(call: ServiceCall):
    measured_at = call.data.get(ATTR_MEASURED_AT) or dt_util.now()
    if measured_at.tzinfo is None:
        measured_at = measured_at.replace(tzinfo=dt_util.get_default_time_zone())
    if measured_at > dt_util.now():
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="measured_at_in_future"
        )
    return measured_at


#: Metrik-Typen, deren neuester Zeitpunkt als "aktueller Stand" gilt
_CURRENT_BODY_TYPES = ("WEIGHT_KG", "BODY_FAT_PERCENTS")


def _newest_body_measurement(coordinator):
    """Time of the newest known weight/body fat measurement."""
    measurements = (coordinator.data or {}).get("measurements") or {}
    newest = None
    for mtype in _CURRENT_BODY_TYPES:
        raw = (measurements.get(mtype) or {}).get("createdAt")
        dt = dt_util.parse_datetime(raw) if isinstance(raw, str) else None
        if dt is not None and (newest is None or dt > newest):
            newest = dt
    return newest


def _fmt(value) -> str:
    """Local date/time, language-neutral (ISO style)."""
    return f"{dt_util.as_local(value):%Y-%m-%d %H:%M}"


async def _notification_texts(
    hass: HomeAssistant, key: str, placeholders: dict[str, str]
) -> tuple[str, str]:
    """Title and message of a notification in the system language
    (translations: exceptions.<key>_title / exceptions.<key>)."""
    prefix = f"component.{DOMAIN}.exceptions.{key}"
    texts: dict[str, str] = {}
    for language in (hass.config.language, "en"):
        strings = await async_get_translations(hass, language, "exceptions", [DOMAIN])
        if f"{prefix}.message" in strings:
            texts = strings
            break
    title = texts.get(f"{prefix}_title.message", "Selection Fitness")
    message = texts.get(f"{prefix}.message", key)
    for name, value in placeholders.items():
        message = message.replace("{" + name + "}", value)
    return title, message


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Registriert die Schreib-Services."""

    async def _add_body(call: ServiceCall) -> None:
        values = {
            k: call.data.get(k) for k in (ATTR_WEIGHT, ATTR_BODY_FAT, ATTR_HEIGHT)
        }
        if values[ATTR_WEIGHT] is None and values[ATTR_BODY_FAT] is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="body_value_required"
            )
        coordinator = _get_coordinator(hass, call)
        if values[ATTR_HEIGHT] is None:
            # Ohne Größe ergänzt der Server selbst die Profilgröße – explizit
            # mitsenden, damit der BMI nachvollziehbar aus bekannten Werten entsteht.
            height = ((coordinator.data or {}).get("profile") or {}).get("height")
            if isinstance(height, (int, float)) and height > 0:
                values[ATTR_HEIGHT] = float(height)
        measured_at = _measured_at(call)
        # Der Server übernimmt jeden gesendeten Wert als aktuelles Profilgewicht,
        # auch wenn er rückwirkend datiert ist. Ältere Werte daher nur bewusst.
        newest = _newest_body_measurement(coordinator)
        backdated = newest is not None and measured_at < newest
        if backdated and not call.data[ATTR_FORCE_BACKDATE]:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="backdated_rejected",
                translation_placeholders={
                    "measured_at": _fmt(measured_at),
                    "newest": _fmt(newest),
                },
            )
        try:
            await coordinator.client.post_body_measurement(
                measured_at=measured_at,
                tz_name=hass.config.time_zone,
                **values,
            )
        except SelectionFitnessApiError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="send_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        if backdated:
            _LOGGER.warning(
                "Backdated body measurement from %s sent - the current weight in the "
                "Selection Fitness profile has been overwritten", measured_at,
            )
            title, message = await _notification_texts(
                hass, "backdated_sent", {"measured_at": _fmt(measured_at)}
            )
            persistent_notification.async_create(
                hass,
                message,
                title=title,
                notification_id=f"{DOMAIN}_backdated_{coordinator.entry.entry_id}",
            )
        await coordinator.async_request_refresh()

    async def _add_cardio(call: ServiceCall) -> None:
        values = {
            k: call.data.get(k)
            for k in (ATTR_RESTING_HEART_RATE, ATTR_SYSTOLIC, ATTR_DIASTOLIC, ATTR_VO2MAX)
        }
        if all(v is None for v in values.values()):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="cardio_value_required"
            )
        if (values[ATTR_SYSTOLIC] is None) != (values[ATTR_DIASTOLIC] is None):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="blood_pressure_incomplete"
            )
        coordinator = _get_coordinator(hass, call)
        try:
            await coordinator.client.post_cardio_measurement(
                measured_at=_measured_at(call),
                tz_name=hass.config.time_zone,
                **values,
            )
        except SelectionFitnessApiError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="send_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await coordinator.async_request_refresh()

    hass.services.async_register(DOMAIN, SERVICE_ADD_BODY, _add_body, schema=BODY_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_ADD_CARDIO, _add_cardio, schema=CARDIO_SCHEMA)

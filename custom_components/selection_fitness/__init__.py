"""Selection Fitness (Netpulse) Integration für Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import (
    SelectionFitnessApiError,
    SelectionFitnessAuthError,
    SelectionFitnessClient,
)
from .const import (
    CONF_BASE_URL,
    CONF_EMAIL,
    CONF_MOBILE_API_URL,
    CONF_PASSWORD,
    DEFAULT_BASE_URL,
    DEFAULT_MOBILE_API_URL,
    DOMAIN,
)
from .coordinator import SelectionFitnessCoordinator
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Registriert die Services (einmal pro Domain)."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Richte einen Config-Entry ein."""
    session = async_get_clientsession(hass)
    # stabile Geräte-UID pro Entry (die API erwartet eine, Inhalt egal)
    device_uid = f"ha-{entry.entry_id[:16]}"

    client = SelectionFitnessClient(
        session=session,
        email=entry.data[CONF_EMAIL],
        password=entry.data[CONF_PASSWORD],
        base_url=entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
        # Mobile-API-Host ist eine feste Brand-Konstante. Immer den aktuellen
        # Default nutzen, damit ein alt gespeicherter (falscher) Wert aus einer
        # früheren Version nicht hängen bleibt.
        mobile_api_url=DEFAULT_MOBILE_API_URL,
        device_uid=device_uid,
    )

    try:
        await client.login()
    except SelectionFitnessAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except SelectionFitnessApiError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = SelectionFitnessCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))

    # Nach dem Anlegen der Entities einmal neu abrufen, damit der
    # (entity-abhängige) Statistik-Import für Gewicht und Kraftmessung
    # sofort läuft statt erst beim nächsten Intervall.
    async def _post_setup_refresh(_now=None) -> None:
        await coordinator.async_refresh()

    hass.async_create_task(_post_setup_refresh())
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Entlade einen Config-Entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok

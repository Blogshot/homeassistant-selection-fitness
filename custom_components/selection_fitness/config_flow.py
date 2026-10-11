"""Config-Flow für Selection Fitness."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

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

_LOGGER = logging.getLogger(__name__)


class SelectionFitnessConfigFlow(ConfigFlow, domain=DOMAIN):
    """Login-Dialog in der HA-Oberfläche."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = SelectionFitnessClient(
                session=session,
                email=user_input[CONF_EMAIL],
                password=user_input[CONF_PASSWORD],
                base_url=user_input.get(CONF_BASE_URL, DEFAULT_BASE_URL),
                mobile_api_url=user_input.get(
                    CONF_MOBILE_API_URL, DEFAULT_MOBILE_API_URL
                ),
                device_uid="ha-config-flow",
            )
            try:
                await client.login()
            except SelectionFitnessAuthError:
                errors["base"] = "invalid_auth"
            except SelectionFitnessApiError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unerwarteter Fehler beim Login")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(client.uuid)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Selection Fitness ({user_input[CONF_EMAIL]})",
                    data=user_input,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_EMAIL): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
                vol.Optional(
                    CONF_MOBILE_API_URL, default=DEFAULT_MOBILE_API_URL
                ): str,
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

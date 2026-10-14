"""Config-Flow für Selection Fitness."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

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
    CONF_PRIMARY_METRIC,
    DEFAULT_BASE_URL,
    DEFAULT_MOBILE_API_URL,
    DEFAULT_PRIMARY_METRIC,
    DOMAIN,
    MACHINE_METRICS,
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

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SelectionFitnessOptionsFlow()


class SelectionFitnessOptionsFlow(OptionsFlow):
    """Optionen: Haupt-Metrik pro Gerät und Abruf-Intervall."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_PRIMARY_METRIC,
                    default=opts.get(CONF_PRIMARY_METRIC, DEFAULT_PRIMARY_METRIC),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=list(MACHINE_METRICS),
                        translation_key="primary_metric",
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    "scan_interval_minutes",
                    default=opts.get("scan_interval_minutes", 30),
                ): vol.All(vol.Coerce(int), vol.Range(min=5, max=360)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

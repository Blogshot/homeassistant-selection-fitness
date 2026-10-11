"""DataUpdateCoordinator für Selection Fitness."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    SelectionFitnessApiError,
    SelectionFitnessAuthError,
    SelectionFitnessClient,
)
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class SelectionFitnessCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Holt in einem Intervall alle verfügbaren Daten."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: SelectionFitnessClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
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
            measurements = await self.client.get_measurements()

            now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            check_in_count = await self.client.get_check_in_count(now)

            return {
                "profile": profile or self.client.profile_login,
                "login": self.client.profile_login,
                "latest_check_in": latest_check_in,
                "check_in_count": check_in_count,
                "workouts": workouts,
                "workout_count": len(workouts),
                "measurements": measurements,
            }
        except SelectionFitnessAuthError as err:
            # Zugangsdaten ungültig -> Reauth auslösen
            raise UpdateFailed(f"Authentifizierung fehlgeschlagen: {err}") from err
        except SelectionFitnessApiError as err:
            raise UpdateFailed(f"API-Fehler: {err}") from err

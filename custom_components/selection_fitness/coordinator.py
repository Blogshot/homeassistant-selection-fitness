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
    extract_machines,
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

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            if self.client.uuid is None:
                await self.client.login()

            profile = await self.client.get_profile()
            latest_check_in = await self.client.get_latest_check_in()
            workouts = await self.client.get_workouts()
            bioage = await self.client.get_bioage()
            # Die /measurements/*/latest-metrics Endpunkte liefern für diese
            # Brand HTTP 500 und sind redundant (Körperwerte kommen aus BioAge,
            # Gewicht/Größe aus dem Profil). Daher nicht mehr abgefragt.
            measurements: dict = {}

            now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            check_in_count = await self.client.get_check_in_count(now)

            firstname = (
                (profile or {}).get("firstname")
                or self.client.profile_login.get("firstname")
                or "Selection Fitness"
            )
            return {
                "firstname": firstname,
                "profile": profile or self.client.profile_login,
                "login": self.client.profile_login,
                "latest_check_in": latest_check_in,
                "check_in_count": check_in_count,
                "workouts": workouts,
                "workout_count": len(workouts),
                "machines": extract_machines(workouts),
                "bioage": bioage,
                "measurements": measurements,
            }
        except SelectionFitnessAuthError as err:
            # Zugangsdaten ungültig -> Reauth auslösen
            raise UpdateFailed(f"Authentifizierung fehlgeschlagen: {err}") from err
        except SelectionFitnessApiError as err:
            raise UpdateFailed(f"API-Fehler: {err}") from err

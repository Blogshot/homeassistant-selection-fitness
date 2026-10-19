"""Config-Flow für Selection Fitness."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    DateTimeSelector,
    DurationSelector,
    DurationSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.util import dt as dt_util

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
from .workout import (
    WorkoutError,
    build_payload,
    describe,
    exercise_attributes,
    exercise_key,
    find_exercise,
    recent_keys,
    summary,
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

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {"workout": WorkoutSubentryFlow}


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


def _seconds(duration: dict[str, Any] | None) -> int:
    """DurationSelector-Wert ({hours, minutes, seconds}) in Sekunden."""
    if not duration:
        return 0
    return (
        int(duration.get("days", 0)) * 86400
        + int(duration.get("hours", 0)) * 3600
        + int(duration.get("minutes", 0)) * 60
        + int(duration.get("seconds", 0))
    )


def _number(min_value: float, max_value: float, step: float, unit: str | None = None):
    config = NumberSelectorConfig(
        min=min_value, max=max_value, step=step, mode=NumberSelectorMode.BOX
    )
    if unit:
        config["unit_of_measurement"] = unit
    return NumberSelector(config)


class WorkoutSubentryFlow(ConfigSubentryFlow):
    """"Workout eintragen": Übung wählen, Werte erfassen, speichern.

    Der Flow legt keinen Subentry an, sondern sendet das Workout und endet mit
    einer Bestätigung (abort "saved"). Ein Workout kann mehrere Übungen und
    je Übung Sätze mit unterschiedlichen Werten enthalten.
    """

    def __init__(self) -> None:
        self._library: list[dict[str, Any]] = []
        self._items: list[dict[str, Any]] = []
        self._exercise: dict[str, Any] | None = None
        self._completed_at = None

    @property
    def _coordinator(self):
        return self.hass.data.get(DOMAIN, {}).get(self._entry_id)

    def _summary(self) -> str:
        return "\n".join(
            f"- {summary(i['ex'], i['sets'], i['values'])}" for i in self._items
        )

    def _exercise_options(self) -> list[SelectOptionDict]:
        """Zuletzt trainierte Übungen zuerst, danach alphabetisch."""
        recent = recent_keys((self._coordinator.data or {}).get("workouts") or [])
        rank = {key: i for i, key in enumerate(recent)}
        exercises = sorted(
            self._library,
            key=lambda ex: (
                rank.get(exercise_key(ex), len(rank)),
                str(ex.get("label")).casefold(),
            ),
        )
        return [
            SelectOptionDict(
                value=exercise_key(ex),
                label=f"{ex['label']} ({(ex.get('category') or {}).get('label', '')})",
            )
            for ex in exercises
        ]

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Übung (und beim ersten Mal den Zeitpunkt) wählen."""
        if self._coordinator is None:
            return self.async_abort(reason="not_loaded")
        if not self._library:
            try:
                self._library = await self._coordinator.client.get_exercise_library()
            except SelectionFitnessApiError:
                return self.async_abort(reason="cannot_connect")

        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                self._exercise = find_exercise(self._library, user_input["exercise"])
            except WorkoutError as err:
                errors["exercise"] = err.args[0]
            if "completed_at" in user_input:
                completed_at = dt_util.parse_datetime(user_input["completed_at"])
                if completed_at is None:
                    errors["completed_at"] = "invalid_time"
                else:
                    if completed_at.tzinfo is None:
                        completed_at = completed_at.replace(
                            tzinfo=dt_util.get_default_time_zone()
                        )
                    if completed_at > dt_util.now():
                        errors["completed_at"] = "in_future"
                    self._completed_at = completed_at
            if not errors:
                return await self.async_step_details()

        fields: dict[Any, Any] = {
            vol.Required("exercise"): SelectSelector(
                SelectSelectorConfig(
                    options=self._exercise_options(),
                    mode=SelectSelectorMode.DROPDOWN,
                    custom_value=True,
                    sort=False,
                )
            )
        }
        if not self._items:
            fields[
                vol.Required(
                    "completed_at",
                    default=dt_util.now().strftime("%Y-%m-%d %H:%M:00"),
                )
            ] = DateTimeSelector()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(fields),
            errors=errors,
            description_placeholders={"summary": self._summary() or "–"},
        )

    async def async_step_details(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Werte passend zum Schema der gewählten Übung erfassen."""
        assert self._exercise is not None
        spec = describe(self._exercise)
        errors: dict[str, str] = {}

        if user_input is not None:
            if spec["sets_code"]:
                one_set = {
                    "reps": user_input.get("reps"),
                    "weight": user_input.get("weight"),
                    "duration": _seconds(user_input.get("duration")),
                }
                sets = [one_set] * int(user_input.get("sets", 1))
                values: dict[str, Any] = {}
            else:
                sets = []
                values = {
                    "duration": _seconds(user_input.get("duration")),
                    "distance": user_input.get("distance"),
                    "calories": user_input.get("calories"),
                }
            try:
                exercise_attributes(self._exercise, sets, values)
            except WorkoutError as err:
                errors["base"] = err.args[0]
            else:
                last = self._items[-1] if self._items else None
                if sets and last and last["ex"] is self._exercise:
                    # weitere Sätze derselben Übung
                    last["sets"].extend(sets)
                else:
                    self._items.append(
                        {"ex": self._exercise, "sets": list(sets), "values": values}
                    )
                return await self.async_step_next()

        fields: dict[Any, Any] = {}
        if spec["sets_code"]:
            fields[vol.Required("sets", default=3)] = _number(1, 20, 1)
            if "reps" in spec["set_fields"]:
                fields[vol.Optional("reps")] = _number(1, 1000, 1)
            if "weight" in spec["set_fields"]:
                fields[vol.Optional("weight")] = _number(0, 1000, 0.5, "kg")
            if "duration" in spec["set_fields"]:
                fields[vol.Optional("duration")] = DurationSelector(
                    DurationSelectorConfig(enable_day=False)
                )
        else:
            fields[vol.Required("duration")] = DurationSelector(
                DurationSelectorConfig(enable_day=False)
            )
            if "distance" in spec["fields"]:
                fields[vol.Optional("distance")] = _number(0, 1000, 0.01, "km")
            if "calories" in spec["fields"]:
                fields[vol.Optional("calories")] = _number(0, 10000, 1, "kcal")
        return self.async_show_form(
            step_id="details",
            data_schema=vol.Schema(fields),
            errors=errors,
            description_placeholders={"exercise": self._exercise["label"]},
        )

    async def async_step_next(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        options = ["add_exercise", "save"]
        if self._items[-1]["sets"]:
            options.insert(0, "add_sets")
        return self.async_show_menu(
            step_id="next",
            menu_options=options,
            description_placeholders={"summary": self._summary()},
        )

    async def async_step_add_sets(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self.async_step_details()

    async def async_step_add_exercise(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self.async_step_user()

    async def async_step_save(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        coordinator = self._coordinator
        if coordinator is None:
            return self.async_abort(reason="not_loaded")
        payload = build_payload(
            [
                {"ex": i["ex"], "attributes": exercise_attributes(i["ex"], i["sets"], i["values"])}
                for i in self._items
            ],
            self._completed_at,
            self.hass.config.time_zone,
        )
        try:
            await coordinator.client.submit_workout(payload)
        except SelectionFitnessApiError as err:
            return self.async_abort(
                reason="send_failed", description_placeholders={"error": str(err)}
            )
        await coordinator.async_request_refresh()
        return self.async_abort(
            reason="saved", description_placeholders={"summary": self._summary()}
        )

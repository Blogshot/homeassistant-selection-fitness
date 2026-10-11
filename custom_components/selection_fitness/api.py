"""Netpulse / Selection Fitness API-Client.

Rekonstruiert aus der Android-App (com.netpulse.mobile.selectionfitness).

Auth-Modell:
  POST {base}/np/exerciser/login   JSON {"login": <email>, "password": <pw>}
    -> Antwort-Body JSON enthält u.a. "uuid"
    -> Set-Cookie: JSESSIONID=...   (Session-Cookie = einzige Autorisierung)
  Folge-Requests: Cookie JSESSIONID + X-NP-* Header.
"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .const import (
    API_VERSION,
    APP_VERSION,
    APP_VERSION_CODE,
    BRAND_NAME,
    BODY_METRIC_TYPES,
    CARDIO_METRIC_TYPES,
)

_LOGGER = logging.getLogger(__name__)


class SelectionFitnessAuthError(Exception):
    """Login fehlgeschlagen (falsche Zugangsdaten o.ä.)."""


class SelectionFitnessApiError(Exception):
    """Allgemeiner API-/Netzwerkfehler."""


class SelectionFitnessClient:
    """Asynchroner Client gegen die Netpulse-Backend-API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        email: str,
        password: str,
        base_url: str,
        mobile_api_url: str,
        device_uid: str,
    ) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._base = base_url.rstrip("/")
        self._mobile = mobile_api_url.rstrip("/")
        self._device_uid = device_uid

        self._session_id: str | None = None  # "JSESSIONID=...."
        self.uuid: str | None = None
        self.profile_login: dict[str, Any] = {}

    # ------------------------------------------------------------------ #
    # Header
    # ------------------------------------------------------------------ #
    def _user_agent(self) -> str:
        parts = {
            "clientType": "MOBILE_DEVICE",
            "devicePlatform": "ANDROID",
            "deviceUid": self._device_uid,
            "applicationName": BRAND_NAME,
            "applicationVersion": APP_VERSION,
            "applicationVersionCode": APP_VERSION_CODE,
        }
        return "; ".join(f"{k}={v}" for k, v in parts.items())

    def _headers(self, with_auth: bool = True) -> dict[str, str]:
        headers = {
            "X-NP-User-Agent": self._user_agent(),
            "X-NP-API-Version": API_VERSION,
            "X-NP-APP-Version": APP_VERSION_CODE,
            "Accept": "application/json",
        }
        if with_auth and self._session_id:
            headers["Cookie"] = self._session_id
        return headers

    # ------------------------------------------------------------------ #
    # Login
    # ------------------------------------------------------------------ #
    async def login(self) -> None:
        """Meldet sich an und speichert uuid + JSESSIONID."""
        url = f"{self._base}/np/exerciser/login"
        # Die App sendet den Login als application/x-www-form-urlencoded
        # (FormBody in der Call-Klasse), NICHT als JSON. aiohttp sendet ein
        # dict unter `data=` genau so form-kodiert.
        # Feldname ist "username" (BranchPlugin.KEY_LOGIN = "username"),
        # nicht "login" – der Wert ist die E-Mail-Adresse.
        payload = {"username": self._email, "password": self._password}
        try:
            async with self._session.post(
                url, data=payload, headers=self._headers(with_auth=False)
            ) as resp:
                body = await resp.text()
                if resp.status == 401:
                    raise SelectionFitnessAuthError("Ungültige Zugangsdaten (401)")
                if resp.status in (400, 403):
                    raise SelectionFitnessAuthError(
                        f"Login abgelehnt (HTTP {resp.status}): {body[:200]}"
                    )
                if resp.status >= 400:
                    raise SelectionFitnessApiError(
                        f"Login-Fehler HTTP {resp.status}: {body[:200]}"
                    )

                data = await resp.json(content_type=None)
                self.uuid = data.get("uuid")
                if not self.uuid:
                    raise SelectionFitnessApiError("Keine uuid in Login-Antwort")
                self.profile_login = data

                # JSESSIONID aus Set-Cookie ziehen
                self._session_id = self._extract_session_cookie(resp)
                if not self._session_id:
                    # Fallback: aiohttp cookie jar
                    for cookie in self._session.cookie_jar:
                        if cookie.key == "JSESSIONID":
                            self._session_id = f"JSESSIONID={cookie.value}"
                            break
                if not self._session_id:
                    raise SelectionFitnessApiError(
                        "Kein JSESSIONID-Cookie in Login-Antwort"
                    )
                _LOGGER.debug("Login ok, uuid=%s", self.uuid)
        except aiohttp.ClientError as err:
            raise SelectionFitnessApiError(f"Netzwerkfehler beim Login: {err}") from err

    @staticmethod
    def _extract_session_cookie(resp: aiohttp.ClientResponse) -> str | None:
        for value in resp.headers.getall("Set-Cookie", []):
            if value.startswith("JSESSIONID="):
                # nur den name=value Teil vor dem ersten ';'
                return value.split(";", 1)[0]
        return None

    # ------------------------------------------------------------------ #
    # Generische GET-Hilfe mit Auto-Relogin bei 401
    # ------------------------------------------------------------------ #
    async def _get(self, url: str, params: dict | None = None) -> Any:
        if self._session_id is None:
            await self.login()
        for attempt in (1, 2):
            try:
                async with self._session.get(
                    url, params=params, headers=self._headers()
                ) as resp:
                    if resp.status == 401 and attempt == 1:
                        _LOGGER.debug("401 bei %s -> Relogin", url)
                        self._session_id = None
                        await self.login()
                        continue
                    text = await resp.text()
                    if resp.status >= 400:
                        raise SelectionFitnessApiError(
                            f"HTTP {resp.status} bei {url}: {text[:200]}"
                        )
                    if not text:
                        return None
                    import json

                    return json.loads(text)
            except aiohttp.ClientError as err:
                raise SelectionFitnessApiError(f"Netzwerkfehler {url}: {err}") from err
        return None

    # ------------------------------------------------------------------ #
    # Datenendpunkte
    # ------------------------------------------------------------------ #
    async def get_profile(self) -> dict[str, Any]:
        """Vollständiges Profil: GET /np/exerciser/{uuid}/profile."""
        url = f"{self._base}/np/exerciser/{self.uuid}/profile"
        data = await self._get(url)
        return data if isinstance(data, dict) else {}

    async def get_latest_check_in(self) -> dict[str, Any] | None:
        """GET /np/exercisers/{uuid}/latest-check-in."""
        url = f"{self._base}/np/exercisers/{self.uuid}/latest-check-in"
        try:
            data = await self._get(url)
        except SelectionFitnessApiError as err:
            _LOGGER.debug("latest-check-in nicht verfügbar: %s", err)
            return None
        return data if isinstance(data, dict) else None

    async def get_check_in_count(self, end_date: str) -> int | None:
        """Anzahl Check-ins: GET /np/exercisers/{uuid}/check-ins/history."""
        url = f"{self._base}/np/exercisers/{self.uuid}/check-ins/history"
        try:
            data = await self._get(url, params={"endDate": end_date})
        except SelectionFitnessApiError as err:
            _LOGGER.debug("check-in history nicht verfügbar: %s", err)
            return None
        if isinstance(data, list):
            return len(data)
        return None

    async def get_workouts(self) -> list[dict[str, Any]]:
        """Workout-Historie: GET /np/exerciser/{uuid}/workouts."""
        url = f"{self._base}/np/exerciser/{self.uuid}/workouts"
        try:
            data = await self._get(url)
        except SelectionFitnessApiError as err:
            _LOGGER.debug("workouts nicht verfügbar: %s", err)
            return []
        # Antwort kann {"workouts":[...]} oder direkt eine Liste sein
        if isinstance(data, dict):
            for key in ("workouts", "data", "items"):
                if isinstance(data.get(key), list):
                    return data[key]
            return []
        if isinstance(data, list):
            return data
        return []

    async def get_measurements(self) -> dict[str, dict[str, Any]]:
        """Aktuelle Körpermesswerte über den Mobile-API-Host.

        GET {mobile}/measurements/api/v1.1/exercisers/{uuid}/{cat}/latest-metrics
        Gibt ein Dict {metric_type: {value, createdAt, source, ...}} zurück.
        Fehler hier lassen den Rest der Integration unberührt.
        """
        result: dict[str, dict[str, Any]] = {}
        categories = {
            "body": BODY_METRIC_TYPES,
            "cardio": CARDIO_METRIC_TYPES,
        }
        for category, types in categories.items():
            url = (
                f"{self._mobile}/measurements/api/v1.1/exercisers/"
                f"{self.uuid}/{category}/latest-metrics"
            )
            params = {"types": ",".join(types), "languageCode": "de"}
            try:
                data = await self._get(url, params=params)
            except SelectionFitnessApiError as err:
                _LOGGER.debug("Messwerte (%s) nicht verfügbar: %s", category, err)
                continue
            if isinstance(data, list):
                for item in data:
                    mtype = item.get("type")
                    if mtype is not None and "value" in item:
                        result[mtype] = item
        return result

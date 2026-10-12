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
from datetime import datetime, timezone
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


def extract_machines(workouts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Fasst die Workout-Historie je Gerät/Übung zusammen.

    Rückgabe: {exerciseCode: {name, source, sessions:[{completedAt, max_weight,
    reps, sets, calories, activity_points}], latest}}
    Nur Geräte mit Gewichtsdaten (Kraft) werden berücksichtigt.
    """
    machines: dict[str, dict[str, Any]] = {}
    for w in workouts or []:
        for ex in w.get("exercises") or []:
            code = ex.get("exerciseCode")
            name = ex.get("name")
            if not code or not name:
                continue
            attrs = ex.get("attributes") or {}
            # Satz-Liste finden (Key beginnt mit "sets_of")
            sets = None
            for k, v in attrs.items():
                if k.startswith("sets_of") and isinstance(v, list):
                    sets = v
                    break
            max_weight: float | None = None
            total_reps = 0
            n_sets = 0
            if sets:
                n_sets = len(sets)
                for s in sets:
                    wv = (s.get("weight") or {}).get("value")
                    rv = (s.get("reps") or {}).get("value")
                    if isinstance(wv, (int, float)):
                        max_weight = wv if max_weight is None else max(max_weight, wv)
                    if isinstance(rv, (int, float)):
                        total_reps += int(rv)
            if max_weight is None:
                # kein Gewicht (z.B. Cardio) -> überspringen
                continue
            # Bild-URL aus der Übungs-Definition (eGym Activity Library)
            exdef = ex.get("exercise") or {}
            image = None
            for key in ("previews", "icons"):
                lst = exdef.get(key)
                if isinstance(lst, list) and lst:
                    image = lst[0]
                    break
            m = machines.setdefault(
                code,
                {
                    "name": name,
                    "source": (ex.get("source") or {}).get("label"),
                    "image": image,
                    "sessions": [],
                },
            )
            if image and not m.get("image"):
                m["image"] = image
            m["sessions"].append(
                {
                    "completedAt": ex.get("completedAt"),
                    "weight": float(max_weight),
                    "reps": total_reps,
                    "sets": n_sets,
                    "calories": (attrs.get("calories") or {}).get("value"),
                    "activity_points": (attrs.get("activity_points") or {}).get("value"),
                    "training_method": (attrs.get("training_method") or {}).get("value"),
                }
            )
    for m in machines.values():
        m["sessions"].sort(key=lambda s: s.get("completedAt") or "")
        m["latest"] = m["sessions"][-1] if m["sessions"] else None
    return machines


def compute_trend(sessions: list[dict[str, Any]], field: str = "weight") -> dict[str, Any]:
    """Trend per linearer Regression über die letzten Sessions für ein
    beliebiges Metrik-Feld. Gibt Richtung, Steigung (pro Monat) und eine
    grobe Prognose für den nächsten Wert zurück."""
    pts: list[tuple[float, float]] = []
    for s in sessions[-8:]:
        ca = s.get("completedAt")
        w = s.get(field)
        if not ca or not isinstance(w, (int, float)):
            continue
        try:
            t = datetime.fromisoformat(ca.replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        pts.append((t, float(w)))
    if len(pts) < 2:
        return {"direction": "unbekannt", "slope_per_month": None, "projected_next": None}
    n = len(pts)
    mean_t = sum(p[0] for p in pts) / n
    mean_w = sum(p[1] for p in pts) / n
    denom = sum((p[0] - mean_t) ** 2 for p in pts)
    if denom == 0:
        return {"direction": "stabil", "slope_per_month": 0.0, "projected_next": round(mean_w, 1)}
    slope = sum((p[0] - mean_t) * (p[1] - mean_w) for p in pts) / denom  # kg pro Sekunde
    slope_month = slope * 86400 * 30
    last_t, last_w = pts[-1]
    # Prognose: nächster Wert bei durchschnittlichem Session-Abstand
    intervals = [pts[i][0] - pts[i - 1][0] for i in range(1, n)]
    avg_iv = sum(intervals) / len(intervals) if intervals else 0
    projected = last_w + slope * avg_iv
    if slope_month > 0.5:
        direction = "steigend"
    elif slope_month < -0.5:
        direction = "fallend"
    else:
        direction = "stabil"
    return {
        "direction": direction,
        "slope_per_month": round(slope_month, 2),
        "projected_next": round(projected, 1),
    }


def _iso8601(style: str = "offset") -> str:
    """Aktuelle Zeit im ISO8601-Format, wie die App es sendet.

    Die App nutzt yyyy-MM-dd'T'HH:mm:ss.SSSZZZZZ -> numerischer Offset
    "+00:00" (style="offset"). Check-ins akzeptieren die Variante ohne
    Offset (style="naive"); "z" hängt literal 'Z' an.
    """
    now = datetime.now(timezone.utc)
    base = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}"
    if style == "offset":
        return base + "+00:00"
    if style == "z":
        return base + "Z"
    return base


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
    async def _get(
        self,
        url: str,
        params: dict | None = None,
        label: str = "",
        quiet_statuses: set[int] | None = None,
    ) -> Any:
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
                    lbl = label or url.rsplit("/np/", 1)[-1][:40]
                    # Erwartete Status (z.B. 404 ohne Mitgliedschaft) nur auf
                    # DEBUG, damit das Log nicht jede Runde zuwarnt.
                    if resp.status >= 400 and resp.status not in (quiet_statuses or set()):
                        _LOGGER.warning(
                            "selfit %s -> HTTP %s: %s",
                            lbl, resp.status, text[:180].replace("\n", " "),
                        )
                    else:
                        _LOGGER.debug(
                            "selfit %s -> HTTP %s (%d bytes)", lbl, resp.status, len(text)
                        )
                    if resp.status >= 400:
                        raise SelectionFitnessApiError(
                            f"HTTP {resp.status} bei {url}: {text[:200]}"
                        )
                    if not text:
                        return None
                    import json

                    return json.loads(text)
            except aiohttp.ClientError as err:
                # Diagnose: Verbindungsfehler sichtbar machen (z.B. Mess-Host
                # nicht erreichbar / DNS), damit die Ursache im Log steht.
                _LOGGER.warning(
                    "selfit-diag %s -> VERBINDUNGSFEHLER: %s",
                    label or url, err,
                )
                raise SelectionFitnessApiError(f"Netzwerkfehler {url}: {err}") from err
        return None

    # ------------------------------------------------------------------ #
    # Datenendpunkte
    # ------------------------------------------------------------------ #
    async def get_profile(self) -> dict[str, Any]:
        """Vollständiges Profil: GET /np/exerciser/{uuid}/profile."""
        url = f"{self._base}/np/exerciser/{self.uuid}/profile"
        data = await self._get(url, label="profile")
        return data if isinstance(data, dict) else {}

    async def get_latest_check_in(self) -> dict[str, Any] | None:
        """GET /np/exercisers/{uuid}/latest-check-in."""
        url = f"{self._base}/np/exercisers/{self.uuid}/latest-check-in"
        try:
            data = await self._get(url, label="latest-check-in", quiet_statuses={404})
        except SelectionFitnessApiError as err:
            _LOGGER.debug("latest-check-in nicht verfügbar: %s", err)
            return None
        return data if isinstance(data, dict) else None

    async def get_check_in_count(self, end_date: str) -> int | None:
        """Anzahl Check-ins: GET /np/exercisers/{uuid}/check-ins/history."""
        url = f"{self._base}/np/exercisers/{self.uuid}/check-ins/history"
        try:
            data = await self._get(
                url,
                params={"endDate": _iso8601("naive")},
                label="check-ins/history",
                quiet_statuses={400, 404},
            )
        except SelectionFitnessApiError as err:
            _LOGGER.debug("check-in history nicht verfügbar: %s", err)
            return None
        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict):
            for key in ("checkIns", "items", "data"):
                if isinstance(data.get(key), list):
                    return len(data[key])
        return None

    async def get_workouts(self) -> list[dict[str, Any]]:
        """Trainings-/Workout-Historie (eGym Advanced Workouts).

        GET {base}/workouts/api/workouts/v2.3/exercisers/{uuid}/workouts
            ?completedAfter=<ISO>&completedBefore=<ISO>&languageCode=de
        Antwort: {"workouts": [ {code, completedAt, workoutPlanLabel,
        exercises:[...], ...}, ... ]}
        """
        url = f"{self._base}/workouts/api/workouts/v2.3/exercisers/{self.uuid}/workouts"
        params = {
            "completedAfter": "2010-01-01T00:00:00.000",
            "completedBefore": _iso8601("naive"),
            "languageCode": "de",
        }
        try:
            data = await self._get(url, params=params, label="workouts-v2.3")
        except SelectionFitnessApiError as err:
            _LOGGER.debug("workouts nicht verfügbar: %s", err)
            return []
        workouts: list[dict[str, Any]] = []
        if isinstance(data, dict):
            for key in ("workouts", "items", "data"):
                if isinstance(data.get(key), list):
                    workouts = data[key]
                    break
        elif isinstance(data, list):
            workouts = data
        return workouts

    async def get_bioage(self) -> dict[str, Any]:
        """eGym BioAge-Summary: Körperalter, Kraft/Muskel, Cardio, Flexibilität,
        Stoffwechsel – plus die zugehörigen Werte.

        GET {mobile}/analysis/api/v1.0/exercisers/{uuid}/bioage
            ?types=strength,cardio,metabolic,flexibility&languageCode=de
        """
        url = f"{self._mobile}/analysis/api/v1.0/exercisers/{self.uuid}/bioage"
        params = {
            "types": "strength,cardio,metabolic,flexibility",
            "languageCode": "de",
        }
        try:
            data = await self._get(url, params=params, label="bioage")
        except SelectionFitnessApiError as err:
            _LOGGER.debug("bioage nicht verfügbar: %s", err)
            return {}
        if not isinstance(data, dict):
            return {}

        def val(section: str, field: str) -> Any:
            sec = data.get(section)
            if not isinstance(sec, dict):
                return None
            node = sec.get(field)
            if isinstance(node, dict):
                return node.get("value")
            return None

        def raw(section: str, field: str) -> Any:
            """Direktes Feld (kein {value:...}-Objekt), z.B. Dysbalance-Status."""
            sec = data.get(section)
            if not isinstance(sec, dict):
                return None
            v = sec.get(field)
            return v if v not in ("", None) else None

        result = {
            "bio_age": val("totalDetails", "totalBioAge"),
            "muscle_age": val("muscleDetails", "muscleBioAge"),
            "upper_body_age": val("muscleDetails", "upperBodyAge"),
            "core_age": val("muscleDetails", "coreAge"),
            "lower_body_age": val("muscleDetails", "lowerBodyAge"),
            "cardio_age": val("cardioDetails", "cardioAge"),
            "resting_heart_rate": val("cardioDetails", "restingHeartRate"),
            "vo2max": val("cardioDetails", "vo2max"),
            "systolic": val("cardioDetails", "systolicPressure"),
            "diastolic": val("cardioDetails", "diastolicPressure"),
            "upper_body_state": raw("muscleDetails", "upperBodyMusclesState"),
            "core_body_state": raw("muscleDetails", "coreBodyMusclesState"),
            "lower_body_state": raw("muscleDetails", "lowerBodyMusclesState"),
            "flexibility_age": val("flexDetails", "flexibilityAge"),
            "metabolic_age": val("metabolicDetails", "metabolicAge"),
            "body_fat": val("metabolicDetails", "bodyFat"),
            "bmi": val("metabolicDetails", "bmi"),
            "waist_hip_ratio": val("metabolicDetails", "waistToHipRatio"),
        }
        # Nur vorhandene Werte behalten
        return {k: v for k, v in result.items() if v is not None}

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
                data = await self._get(url, params=params, label=f"measure/{category}")
            except SelectionFitnessApiError as err:
                _LOGGER.debug("Messwerte (%s) nicht verfügbar: %s", category, err)
                continue
            if isinstance(data, list):
                for item in data:
                    mtype = item.get("type")
                    if mtype is not None and "value" in item:
                        result[mtype] = item
        return result

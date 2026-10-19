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
from datetime import datetime, timedelta, timezone
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


def counted_workouts(workouts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Workouts für die Workout-Anzahl: Studio und manuell eingetragen, ohne
    reine Einträge verbundener Apps (z. B. FitBit "Tägliche Routine")."""
    return [
        w
        for w in workouts or []
        if any(
            (e.get("source") or {}).get("code") != "connected_app"
            for e in w.get("exercises") or []
        )
    ]


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
        return {"direction": "stable", "slope_per_month": 0.0, "projected_next": round(mean_w, 1)}
    slope = sum((p[0] - mean_t) * (p[1] - mean_w) for p in pts) / denom  # kg pro Sekunde
    slope_month = slope * 86400 * 30
    last_t, last_w = pts[-1]
    # Prognose: nächster Wert bei durchschnittlichem Session-Abstand
    intervals = [pts[i][0] - pts[i - 1][0] for i in range(1, n)]
    avg_iv = sum(intervals) / len(intervals) if intervals else 0
    projected = last_w + slope * avg_iv
    if slope_month > 0.5:
        direction = "rising"
    elif slope_month < -0.5:
        direction = "falling"
    else:
        direction = "stable"
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


#: Frühestes Jahr, bis zu dem die Historie zurück abgefragt wird.
HISTORY_MIN_YEAR = 2015

#: Übungskatalog ändert sich selten und ist groß (~2000 Einträge)
LIBRARY_CACHE_TTL = timedelta(hours=24)

#: Schutz gegen Endlosschleifen beim seitenweisen Laden (je Seite 1000 Übungen)
WORKOUT_MAX_PAGES = 50


def _merge_workouts(
    base: list[dict[str, Any]], newer: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Workouts nach Code zusammenführen; bei Dubletten gewinnt die Fassung
    mit mehr Übungen (an Seitengrenzen schneidet der Server Workouts ab)."""
    merged = {w["code"]: w for w in base}
    for w in newer:
        old = merged.get(w["code"])
        if old is None or len(w.get("exercises") or []) >= len(old.get("exercises") or []):
            merged[w["code"]] = w
    return sorted(merged.values(), key=lambda w: w["completedAt"], reverse=True)


def _year_windows_desc(min_year: int = HISTORY_MIN_YEAR):
    """Liefert (Jahr, startDate, endDate) absteigend vom aktuellen Jahr bis
    min_year. Der Server gibt pro Fenster nur ein Jahr zurück, daher wird je
    Kalenderjahr ein eigenes Fenster erzeugt."""
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    for year in range(now.year, min_year - 1, -1):
        start = f"{year}-01-01"
        end = today if year == now.year else f"{year}-12-31"
        yield year, start, end


def _parse_history_date(raw: Any) -> datetime | None:
    """Parst ein History-Datum robust: ISO-String (mit/ohne Zeit/Offset),
    reines Datum (yyyy-MM-dd) oder Epoch-Millis. Rückgabe tz-aware (UTC)."""
    # Epoch in Millisekunden
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(float(raw) / 1000.0, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y-%m", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


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
        language: str = "de",
    ) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._base = base_url.rstrip("/")
        self._mobile = mobile_api_url.rstrip("/")
        self._device_uid = device_uid
        # Language for names/texts from the API (ISO 639-1, e.g. "de" from "de-CH")
        self._language = (language or "de").split("-")[0].lower()

        self._session_id: str | None = None  # "JSESSIONID=...."
        self.uuid: str | None = None
        self.profile_login: dict[str, Any] = {}
        self._library_cache: tuple[datetime, list[dict[str, Any]]] | None = None
        # Vollständige Workout-Historie (None = noch nicht komplett geladen)
        self._workouts_cache: list[dict[str, Any]] | None = None

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
                    raise SelectionFitnessAuthError("Invalid credentials (401)")
                if resp.status in (400, 403):
                    raise SelectionFitnessAuthError(
                        f"Login rejected (HTTP {resp.status}): {body[:200]}"
                    )
                if resp.status >= 400:
                    raise SelectionFitnessApiError(
                        f"Login error HTTP {resp.status}: {body[:200]}"
                    )

                data = await resp.json(content_type=None)
                self.uuid = data.get("uuid")
                if not self.uuid:
                    raise SelectionFitnessApiError("No uuid in login response")
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
                        "No JSESSIONID cookie in login response"
                    )
                _LOGGER.debug("Login ok, uuid=%s", self.uuid)
        except aiohttp.ClientError as err:
            raise SelectionFitnessApiError(f"Network error during login: {err}") from err

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
                        _LOGGER.debug("401 at %s -> re-login", url)
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
                            f"HTTP {resp.status} at {url}: {text[:200]}"
                        )
                    if not text:
                        return None
                    import json

                    return json.loads(text)
            except aiohttp.ClientError as err:
                # Diagnose: Verbindungsfehler sichtbar machen (z.B. Mess-Host
                # nicht erreichbar / DNS), damit die Ursache im Log steht.
                _LOGGER.warning(
                    "selfit-diag %s -> CONNECTION ERROR: %s",
                    label or url, err,
                )
                raise SelectionFitnessApiError(f"Network error {url}: {err}") from err
        return None

    # ------------------------------------------------------------------ #
    # Generische POST-Hilfe (JSON) mit Auto-Relogin bei 401
    # ------------------------------------------------------------------ #
    async def _post_json(self, url: str, payload: dict[str, Any], label: str = "") -> str:
        return await self._send("POST", url, payload, label)

    async def _send(
        self, method: str, url: str, payload: dict[str, Any] | None, label: str = ""
    ) -> str:
        if self._session_id is None:
            await self.login()
        for attempt in (1, 2):
            try:
                async with self._session.request(
                    method, url, json=payload, headers=self._headers()
                ) as resp:
                    if resp.status == 401 and attempt == 1:
                        _LOGGER.debug("401 at %s -> re-login", url)
                        self._session_id = None
                        await self.login()
                        continue
                    text = await resp.text()
                    _LOGGER.debug(
                        "selfit %s %s -> HTTP %s: %s",
                        method, label or url, resp.status, text[:180].replace("\n", " "),
                    )
                    if resp.status >= 400:
                        raise SelectionFitnessApiError(
                            f"HTTP {resp.status} at {url}: {text[:200]}"
                        )
                    return text
            except aiohttp.ClientError as err:
                raise SelectionFitnessApiError(f"Network error {url}: {err}") from err
        raise SelectionFitnessApiError(f"401 again at {url} after re-login")

    # ------------------------------------------------------------------ #
    # Schreibende Endpunkte (Health-Connect-Sync der App)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _completed_at(measured_at: datetime, tz_name: str) -> str:
        """completedAt im App-Format yyyy-MM-dd'T'HH:mm:ss.SSSSSS.

        Die App formatiert in UTC, der Server interpretiert den Wert aber als
        Ortszeit der mitgesendeten Zeitzone (getestet: 18:00 + Europe/Berlin
        -> gespeichert 16:00Z). Daher wird in die Ortszeit umgerechnet.
        """
        from zoneinfo import ZoneInfo

        if measured_at.tzinfo is None:
            measured_at = measured_at.replace(tzinfo=ZoneInfo(tz_name))
        local = measured_at.astimezone(ZoneInfo(tz_name))
        return local.strftime("%Y-%m-%dT%H:%M:%S.%f")

    async def _post_connected_measurement(
        self,
        category: str,
        values: dict[str, Any],
        measured_at: datetime,
        tz_name: str,
        source: str,
    ) -> None:
        payload: dict[str, Any] = {
            "appName": "healthConnect",
            "originalSource": source,
            "timezone": tz_name,
            "completedAt": self._completed_at(measured_at, tz_name),
        }
        # Die App lässt leere Felder weg (JsonInclude.NON_NULL).
        payload.update({k: v for k, v in values.items() if v is not None})
        url = (
            f"{self._mobile}/connected-app-measurements/api/v1.0/"
            f"exerciser/{self.uuid}/{category}"
        )
        await self._post_json(url, payload, label=f"measure/{category}")

    async def post_body_measurement(
        self,
        measured_at: datetime,
        tz_name: str,
        weight: float | None = None,
        body_fat: float | None = None,
        height: float | None = None,
        source: str = "Home Assistant",
    ) -> None:
        """Körperwerte schreiben: POST {mobile}/connected-app-measurements/
        api/v1.0/exerciser/{uuid}/bmi  (kg, %, cm).

        Achtung: fehlt `height`, ergänzt der Server die aktuelle Profilgröße
        und berechnet daraus den BMI. Einträge lassen sich nicht löschen.
        """
        await self._post_connected_measurement(
            "bmi",
            {"weight": weight, "bodyFat": body_fat, "height": height},
            measured_at, tz_name, source,
        )

    async def post_cardio_measurement(
        self,
        measured_at: datetime,
        tz_name: str,
        resting_heart_rate: int | None = None,
        systolic: int | None = None,
        diastolic: int | None = None,
        vo2max: float | None = None,
        source: str = "Home Assistant",
    ) -> None:
        """Cardio-Werte schreiben: POST {mobile}/connected-app-measurements/
        api/v1.0/exerciser/{uuid}/cardio."""
        await self._post_connected_measurement(
            "cardio",
            {
                "bpm": resting_heart_rate,
                "systolic": systolic,
                "diastolic": diastolic,
                "vo2max": vo2max,
            },
            measured_at, tz_name, source,
        )

    # ------------------------------------------------------------------ #
    # Manuelle Workouts (eGym Advanced Workouts, "Training eintragen")
    # ------------------------------------------------------------------ #
    async def get_exercise_library(self) -> list[dict[str, Any]]:
        """Übungskatalog aller Bibliotheken (gecacht, ~2000 Übungen).

        GET {base}/workouts/api/exercise-libraries/v2.1/exercisers/{uuid}/
            exercise-libraries?languageCode=de
        Rückgabe: Übungen mit zusätzlichem Feld "libraryCode".
        """
        now = datetime.now(timezone.utc)
        if self._library_cache and now - self._library_cache[0] < LIBRARY_CACHE_TTL:
            return self._library_cache[1]
        if self.uuid is None:
            await self.login()
        url = (
            f"{self._base}/workouts/api/exercise-libraries/v2.1/"
            f"exercisers/{self.uuid}/exercise-libraries"
        )
        data = await self._get(
            url, params={"languageCode": self._language}, label="exercise-libraries"
        )
        exercises: list[dict[str, Any]] = []
        for lib in (data or {}).get("libraries") or []:
            for ex in lib.get("exercises") or []:
                if ex.get("code") and ex.get("label"):
                    exercises.append({**ex, "libraryCode": lib.get("code")})
        self._library_cache = (now, exercises)
        return exercises

    async def submit_workout(self, payload: dict[str, Any]) -> str | None:
        """Workout mit einer oder mehreren Übungen eintragen.

        POST {base}/workouts/api/workouts/v2.0/exercisers/{uuid}/workouts
        Antwort: {"code": <workoutCode>}. Kalorien und Aktivitätspunkte
        berechnet der Server selbst; Einträge erscheinen als Quelle "manual"
        und lassen sich wieder löschen.
        """
        url = f"{self._base}/workouts/api/workouts/v2.0/exercisers/{self.uuid}/workouts"
        text = await self._post_json(url, payload, label="submit-workout")
        try:
            import json

            return (json.loads(text) or {}).get("code")
        except ValueError:
            return None

    async def delete_workout_exercise(self, workout_code: str, exercise_code: str) -> None:
        """Eine Übung aus der Historie löschen (nur manuelle, deletable=true).

        DELETE {base}/workouts/api/workouts/v2.0/exercisers/{uuid}/workouts/
            {workoutCode}/exercises/{exerciseCode}
        """
        url = (
            f"{self._base}/workouts/api/workouts/v2.0/exercisers/{self.uuid}/"
            f"workouts/{workout_code}/exercises/{exercise_code}"
        )
        await self._send("DELETE", url, None, label="delete-exercise")

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
            _LOGGER.debug("latest-check-in unavailable: %s", err)
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
            _LOGGER.debug("check-in history unavailable: %s", err)
            return None
        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict):
            for key in ("checkIns", "items", "data"):
                if isinstance(data.get(key), list):
                    return len(data[key])
        return None

    async def get_workouts(self) -> list[dict[str, Any]] | None:
        """Trainings-/Workout-Historie (eGym Advanced Workouts), vollständig.

        GET {base}/workouts/api/workouts/v2.3/exercisers/{uuid}/workouts
            ?completedAfter=<ISO>&completedBefore=<ISO>&languageCode=de
        Antwort: {"workouts": [ {code, completedAt, workoutPlanLabel,
        exercises:[...], ...}, ... ]}

        Der Server liefert je Anfrage höchstens 1000 Übungen (neueste zuerst)
        und schneidet dabei auch das älteste Workout mittendrin ab. Die
        komplette Historie wird daher einmal seitenweise rückwärts geladen
        (completedBefore = ältestes Workout + 1 s, vollständigere Fassung
        gewinnt); danach genügt die neueste Seite, ältere Workouts kommen aus
        dem Cache. Rückgabe None bei Fehlern.
        """
        try:
            page = await self._get_workouts_page(_iso8601("naive"))
            if not page:
                self._workouts_cache = []
                return []
            boundary = min(w["completedAt"] for w in page)
            if self._workouts_cache is None:
                older = await self._get_workouts_before(boundary)
            else:
                older = [w for w in self._workouts_cache if w["completedAt"] <= boundary]
        except SelectionFitnessApiError as err:
            _LOGGER.debug("workouts unavailable: %s", err)
            return None
        workouts = _merge_workouts(older, page)
        self._workouts_cache = workouts
        return workouts

    async def _get_workouts_before(self, boundary: str) -> list[dict[str, Any]]:
        """Alle Workouts bis einschließlich `boundary` (seitenweise)."""
        collected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for _ in range(WORKOUT_MAX_PAGES):
            before = _parse_history_date(boundary) + timedelta(seconds=1)
            page = await self._get_workouts_page(before.strftime("%Y-%m-%dT%H:%M:%S.000"))
            new = [w for w in page if w["code"] not in seen]
            collected = _merge_workouts(collected, page)
            seen.update(w["code"] for w in page)
            oldest = min((w["completedAt"] for w in page), default=boundary)
            if not new or oldest >= boundary:
                break
            boundary = oldest
        return collected

    async def _get_workouts_page(self, completed_before: str) -> list[dict[str, Any]]:
        url = f"{self._base}/workouts/api/workouts/v2.3/exercisers/{self.uuid}/workouts"
        params = {
            "completedAfter": "2010-01-01T00:00:00.000",
            "completedBefore": completed_before,
            "languageCode": self._language,
        }
        data = await self._get(url, params=params, label="workouts-v2.3")
        workouts: list[dict[str, Any]] = []
        if isinstance(data, dict):
            for key in ("workouts", "items", "data"):
                if isinstance(data.get(key), list):
                    workouts = data[key]
                    break
        elif isinstance(data, list):
            workouts = data
        return [w for w in workouts if w.get("code") and w.get("completedAt")]

    async def get_bioage(self) -> dict[str, Any]:
        """eGym BioAge-Summary: Körperalter, Kraft/Muskel, Cardio, Flexibilität,
        Stoffwechsel – plus die zugehörigen Werte.

        GET {mobile}/analysis/api/v1.0/exercisers/{uuid}/bioage
            ?types=strength,cardio,metabolic,flexibility&languageCode=de
        """
        url = f"{self._mobile}/analysis/api/v1.0/exercisers/{self.uuid}/bioage"
        # Alle bekannten Kategorien anfragen (App-Namensvarianten abgedeckt:
        # muscle/strength, metabolic/body, cardio, flexibility).
        params = {
            "types": "muscle,strength,cardio,metabolic,body,flexibility",
            "languageCode": self._language,
        }
        try:
            data = await self._get(url, params=params, label="bioage")
        except SelectionFitnessApiError as err:
            _LOGGER.debug("bioage unavailable: %s", err)
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
            "flexibility_age": val("flexibilityDetails", "flexibilityAge"),
            "metabolic_age": val("metabolicDetails", "metabolicAge"),
            "body_fat": val("metabolicDetails", "bodyFat"),
            "bmi": val("metabolicDetails", "bmi"),
            "waist_hip_ratio": val("metabolicDetails", "waistToHipRatio"),
        }
        # Nur vorhandene Werte behalten
        return {k: v for k, v in result.items() if v is not None}

    async def get_strength(self) -> dict[str, dict[str, Any]]:
        """eGym Kraftmessung je Gerät (fester Testwert, unabhängig vom
        eingestellten Gewicht).

        GET {mobile}/measurements/api/v1.0/exercisers/{uuid}/strength/latest
        Antwort: Liste von {exercise:{code,label,icons}, strength:{value,
        progress,percentageDiff,createdAt}, bodyRegion, ...}
        Rückgabe: {exerciseCode: {value, progress, change_pct, created_at,
        label, image, body_region}}
        """
        url = f"{self._mobile}/measurements/api/v1.0/exercisers/{self.uuid}/strength/latest"
        try:
            data = await self._get(url, params={"languageCode": self._language}, label="strength")
        except SelectionFitnessApiError as err:
            _LOGGER.debug("strength unavailable: %s", err)
            return {}
        result: dict[str, dict[str, Any]] = {}
        # Liste liegt unter "strengthMeasurements" (Fallbacks defensiv)
        items = data if isinstance(data, list) else None
        if items is None and isinstance(data, dict):
            for key in ("strengthMeasurements", "measurements", "items"):
                if isinstance(data.get(key), list):
                    items = data[key]
                    break
        if not isinstance(items, list):
            return {}
        for it in items:
            if not isinstance(it, dict):
                continue
            ex = it.get("exercise") or {}
            label = ex.get("label")
            strength = it.get("strength") or {}
            if not label or "value" not in strength:
                continue
            icons = ex.get("icons")
            # Merge erfolgt über den Namen (Kraftmess-Codes != Trainings-Codes)
            result[str(label)] = {
                "value": strength.get("value"),
                "progress": strength.get("progress"),
                "change_pct": strength.get("percentageDiff"),
                "created_at": it.get("createdAt") or strength.get("createdAt"),
                "label": label,
                "image": icons[0] if isinstance(icons, list) and icons else None,
                "body_region": it.get("bodyRegion") or ex.get("bodyRegion"),
                "strength_code": ex.get("code"),
            }
        return result

    async def get_strength_history(
        self, exercise_id: str
    ) -> list[tuple[datetime, float]]:
        """Historie der Kraftmessung für ein Gerät (strength-Test-exerciseId).

        Der Server liefert pro Abfragefenster nur ~1 Jahr (die App schaltet
        zwischen Jahren um). Daher Jahr für Jahr abfragen und zusammenführen;
        Früh-Stopp nach zwei aufeinanderfolgenden leeren Jahren.
        Rückgabe: sortierte, deduplizierte Liste (Zeitpunkt, Wert).
        """
        merged: dict[datetime, float] = {}
        empty_streak = 0
        for _year, start, end in _year_windows_desc():
            pts = await self._get_strength_history_window(
                str(exercise_id), start, end
            )
            if pts:
                empty_streak = 0
                for dt, val in pts:
                    merged[dt] = val
            else:
                empty_streak += 1
                if empty_streak >= 2:
                    break
        return sorted(merged.items(), key=lambda p: p[0])

    async def _get_strength_history_window(
        self, exercise_id: str, start_date: str, end_date: str
    ) -> list[tuple[datetime, float]]:
        """Eine Kraftmess-Historie für ein einzelnes Jahresfenster.

        GET {mobile}/measurements/api/v1.0/exercisers/{uuid}/strength
            ?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD&exerciseId=<code>&languageCode=de
        """
        url = f"{self._mobile}/measurements/api/v1.0/exercisers/{self.uuid}/strength"
        params = {
            "startDate": start_date,
            "endDate": end_date,
            "exerciseId": str(exercise_id),
            "languageCode": self._language,
        }
        try:
            data = await self._get(url, params=params, label="strength-history")
        except SelectionFitnessApiError as err:
            _LOGGER.debug("strength-history unavailable: %s", err)
            return []
        items = data if isinstance(data, list) else None
        if items is None and isinstance(data, dict):
            for key in ("strengthMeasurements", "measurements", "items"):
                if isinstance(data.get(key), list):
                    items = data[key]
                    break
        points: list[tuple[datetime, float]] = []
        if not isinstance(items, list):
            return []
        for it in items:
            if not isinstance(it, dict):
                continue
            strength = it.get("strength") or {}
            # Top-Level createdAt ist der echte Messzeitpunkt;
            # strength.createdAt ist teils 1970 (Platzhalter).
            ca = it.get("createdAt") or strength.get("createdAt")
            val = strength.get("value")
            if not ca or not isinstance(val, (int, float)):
                continue
            try:
                dt = datetime.fromisoformat(ca.replace("Z", "+00:00"))
            except ValueError:
                continue
            points.append((dt, float(val)))
        points.sort(key=lambda p: p[0])
        return points

    async def get_bioage_history(self) -> dict[str, list[tuple[datetime, float]]]:
        """Historie der BioAge-/Fitnessalter-Werte (zurück bis zur ersten
        Messung, oft Jahre vor der aktuellen App-Installation).

        Der Server liefert pro Fenster nur ~1 Jahr (die App schaltet zwischen
        Jahren um). Daher Jahr für Jahr abfragen und zusammenführen;
        Früh-Stopp nach zwei aufeinanderfolgenden leeren Jahren.

        GET {mobile}/analysis/api/v1.0/exercisers/{uuid}/bioage/history
            ?types=TOTAL,MUSCLE,CARDIO,METABOLIC,FLEXIBILITY
            &startDate=YYYY-MM-DD&endDate=YYYY-MM-DD
            &granularity=ONE_ITEM_PER_MONTH&timezone=Europe/Berlin
        Antwort: [{"type": "TOTAL", "history": [{"date": "...", "value": 28.0}]}]
        Rückgabe: {analysisType: [(Zeitpunkt, Wert), ...]} (je sortiert).
        """
        merged: dict[str, dict[datetime, float]] = {}
        empty_streak = 0
        for _year, start, end in _year_windows_desc():
            window = await self._get_bioage_history_window(start, end)
            if window:
                empty_streak = 0
                for mtype, pts in window.items():
                    bucket = merged.setdefault(mtype, {})
                    for dt, val in pts:
                        bucket[dt] = val
            else:
                empty_streak += 1
                if empty_streak >= 2:
                    break
        return {
            mtype: sorted(pts.items(), key=lambda p: p[0])
            for mtype, pts in merged.items()
        }

    async def _get_bioage_history_window(
        self, start_date: str, end_date: str
    ) -> dict[str, list[tuple[datetime, float]]]:
        """BioAge-Historie für ein Jahresfenster. Wie die App je Fenster einen
        Typ pro Request abfragen (TOTAL/MUSCLE/CARDIO/METABOLIC/FLEXIBILITY)."""
        result: dict[str, list[tuple[datetime, float]]] = {}
        for mtype in ("TOTAL", "MUSCLE", "CARDIO", "METABOLIC", "FLEXIBILITY"):
            points = await self._get_bioage_history_type(
                mtype, start_date, end_date
            )
            if points:
                result[mtype] = points
        return result

    async def _get_bioage_history_type(
        self, mtype: str, start_date: str, end_date: str
    ) -> list[tuple[datetime, float]]:
        """Ein einzelner Alters-Typ für ein Jahresfenster (ein Request, genau
        wie die App: getAnalysisMetricHistory(listOf(type), …))."""
        url = f"{self._mobile}/analysis/api/v1.0/exercisers/{self.uuid}/bioage/history"
        params = {
            "types": mtype,
            "startDate": start_date,
            "endDate": end_date,
            "granularity": "ONE_ITEM_PER_MONTH",
            "timezone": "Europe/Berlin",
        }
        try:
            data = await self._get(
                url, params=params, label="bioage-history", quiet_statuses={404}
            )
        except SelectionFitnessApiError as err:
            _LOGGER.debug("bioage-history (%s) unavailable: %s", mtype, err)
            return []
        # Antwort: Liste von {type, history:[{date,value}]} (ggf. unter Schlüssel)
        series = data if isinstance(data, list) else None
        if series is None and isinstance(data, dict):
            for key in ("history", "histories", "metrics", "items"):
                if isinstance(data.get(key), list):
                    series = data[key]
                    break
        if not isinstance(series, list):
            return []
        points: list[tuple[datetime, float]] = []
        for entry in series:
            if not isinstance(entry, dict):
                continue
            # Passenden Typ herausfiltern (Server könnte mehr zurückgeben)
            etype = entry.get("type")
            if etype and str(etype) != mtype:
                continue
            hist = entry.get("history")
            if not isinstance(hist, list):
                continue
            for it in hist:
                if not isinstance(it, dict):
                    continue
                raw = it.get("date")
                val = it.get("value")
                if raw is None or not isinstance(val, (int, float)):
                    continue
                dt = _parse_history_date(raw)
                if dt is None:
                    continue
                points.append((dt, float(val)))
        return points

    async def get_body_measurement_log(self, full: bool = False) -> list[dict[str, Any]]:
        """Körpermessungen (manuell, Waage im Studio, Health Connect …).

        GET {mobile}/measurements/api/v1.0/exercisers/{uuid}/body-measurements
            ?startDate=yyyy-MM-dd&endDate=yyyy-MM-dd
        Der Server liefert je Fenster nur ein Jahr und ältere Einträge teils
        mehrfach; daher jahresweise abfragen und deduplizieren.
        full=False fragt nur das laufende Jahr ab.
        Rückgabe: [{created_at: datetime, createdAt, source, sourceLabel,
        metrics: {TYPE: value}}], aufsteigend nach Zeit.
        """
        url = f"{self._mobile}/measurements/api/v1.0/exercisers/{self.uuid}/body-measurements"
        windows = list(_year_windows_desc())
        if not full:
            windows = windows[:1]
        seen: set[tuple] = set()
        entries: list[dict[str, Any]] = []
        for _year, start, end in windows:
            data = await self._get(
                url, params={"startDate": start, "endDate": end}, label="body-measurements"
            )
            items = (data or {}).get("measurements") if isinstance(data, dict) else data
            for it in items or []:
                metrics = {
                    m.get("type"): m.get("value")
                    for m in it.get("metrics") or []
                    if m.get("type") and isinstance(m.get("value"), (int, float))
                }
                created_at = _parse_history_date(it.get("createdAt"))
                if not metrics or created_at is None:
                    continue
                key = (it.get("createdAt"), tuple(sorted(metrics.items())))
                if key in seen:
                    continue
                seen.add(key)
                entries.append(
                    {
                        "created_at": created_at,
                        "createdAt": it.get("createdAt"),
                        "source": it.get("source"),
                        "sourceLabel": it.get("sourceLabel"),
                        "metrics": metrics,
                    }
                )
        entries.sort(key=lambda e: e["created_at"])
        return entries

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
            params = {"types": ",".join(types), "languageCode": self._language}
            try:
                data = await self._get(url, params=params, label=f"measure/{category}")
            except SelectionFitnessApiError as err:
                _LOGGER.debug("Measurements (%s) unavailable: %s", category, err)
                continue
            if isinstance(data, list):
                for item in data:
                    mtype = item.get("type")
                    if mtype is not None and "value" in item:
                        result[mtype] = item
        return result

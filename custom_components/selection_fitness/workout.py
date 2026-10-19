"""Manuelle Workouts: Übungskatalog auswerten und Payload bauen.

Jede Übung im eGym-Katalog bringt ein Attribut-Schema mit. In der Praxis gibt
es zwei Formen (Stand App 1.7, ~2000 Übungen):

* Sätze ("sets"): Liste von Elementen, jedes Element ist eine Variante aus
  reps/duration (+ weight, + recovery_time), z. B.
  sets_of_reps_and_weight_or_duration_and_weight.
* Einfache Werte ("simple"): duration, distance, calories (Cardio, Kurse).

Kalorien und Aktivitätspunkte von Satz-Übungen berechnet der Server selbst.
Payload-Format wie ExercisesToSubmitExercisesDTOConverter der App.
"""
from __future__ import annotations

from datetime import datetime
from itertools import groupby
from typing import Any
from zoneinfo import ZoneInfo

#: Werte, die pro Satz erfasst werden können
SET_FIELDS = ("reps", "weight", "duration")
#: Einfache Werte, die erfasst werden (activity_points berechnet der Server)
SIMPLE_FIELDS = ("duration", "distance", "calories")

# Einheiten wie in der App (metrisch); Dauer immer in Sekunden
_UNITS = {
    "reps": "unit",
    "weight": "kg",
    "duration": "sec",
    "distance": "km",
    "calories": "kcal",
}


class WorkoutError(Exception):
    """Ungültige Eingabe; args[0] ist der Übersetzungsschlüssel."""


def exercise_key(ex: dict[str, Any]) -> str:
    return f"{ex.get('libraryCode')}:{ex.get('code')}"


def _variants(element: dict[str, Any]) -> list[set[str]]:
    """Mögliche Feldkombinationen eines Satz-Elements."""
    etype = element.get("type")
    if etype == "union":
        out: list[set[str]] = []
        for allowed in element.get("allowedTypes") or []:
            out.extend(_variants(allowed))
        return out
    if etype == "bucket":
        return [{n.get("code") for n in element.get("nestedElements") or []}]
    if etype == "simple":
        return [{element.get("code")}]
    return []


def describe(ex: dict[str, Any]) -> dict[str, Any]:
    """Formular-Beschreibung einer Übung.

    {"sets_code": str|None, "variants": [set], "set_fields": [..],
     "fields": [..], "required": [..]}
    """
    sets_code = None
    variants: list[set[str]] = []
    fields: list[str] = []
    required: list[str] = []
    for attr in ex.get("attributes") or []:
        if attr.get("type") == "sets":
            sets_code = attr.get("code")
            variants = [
                v for v in _variants(attr.get("elementType") or {})
                if v & {"reps", "duration"}
            ]
        elif attr.get("type") == "simple" and attr.get("code") in SIMPLE_FIELDS:
            fields.append(attr["code"])
            if attr.get("required"):
                required.append(attr["code"])
    set_fields = [f for f in SET_FIELDS if any(f in v for v in variants)]
    return {
        "sets_code": sets_code if variants else None,
        "variants": variants,
        "set_fields": set_fields,
        "fields": [] if variants else fields,
        "required": [] if variants else required,
    }


def _value(field: str, value: Any) -> dict[str, Any]:
    if field == "weight" or field == "distance":
        return {"unit": _UNITS[field], "value": float(value)}
    return {"unit": _UNITS[field], "value": int(value)}


def build_set(spec: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    """Ein Satz-Element passend zu einer Variante der Übung."""
    wanted = "reps" if values.get("reps") else "duration" if values.get("duration") else None
    if wanted is None:
        raise WorkoutError("reps_or_duration_required")
    variant = next((v for v in spec["variants"] if wanted in v), None)
    if variant is None:
        raise WorkoutError("reps_or_duration_required")
    element = {wanted: _value(wanted, values[wanted])}
    if "weight" in variant:
        # Gewicht ist in diesen Varianten Pflicht (0 = Körpergewicht)
        element["weight"] = _value("weight", values.get("weight") or 0)
    return element


def build_simple(spec: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    attrs = {
        f: _value(f, values[f])
        for f in spec["fields"]
        if values.get(f) not in (None, 0, 0.0)
    }
    if not attrs or any(f not in attrs for f in spec["required"]):
        raise WorkoutError("duration_required")
    return attrs


def _local_z(at: datetime, tz_name: str) -> str:
    # Wie die App: Ortszeit mit literalem "Z"; der Server wertet sie
    # zusammen mit "timezone" korrekt aus (getestet).
    return at.astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_payload(
    exercises: list[dict[str, Any]], completed_at: datetime, tz_name: str
) -> dict[str, Any]:
    """Workout-Payload aus [{"ex": <Katalogübung>, "attributes": {...}}]."""
    utc = completed_at.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "timezone": tz_name,
        "completedAt": utc,
        "workoutPlanCode": None,
        "exercises": [
            {
                "libraryCode": item["ex"].get("libraryCode"),
                "exerciseCode": item["ex"].get("code"),
                "exerciseVersion": item["ex"].get("version") or 1,
                "completedAt": _local_z(completed_at, tz_name),
                "timezone": tz_name,
                "attributes": item["attributes"],
            }
            for item in exercises
        ],
    }


def exercise_attributes(
    ex: dict[str, Any], sets: list[dict[str, Any]], values: dict[str, Any]
) -> dict[str, Any]:
    """Attribute einer Übung aus Sätzen bzw. einfachen Werten."""
    spec = describe(ex)
    if spec["sets_code"]:
        if not sets:
            raise WorkoutError("reps_or_duration_required")
        return {spec["sets_code"]: [build_set(spec, s) for s in sets]}
    return build_simple(spec, values)


def find_exercise(library: list[dict[str, Any]], query: str) -> dict[str, Any]:
    """Übung über "lib:code", Code oder exakten Namen finden."""
    q = str(query).strip()
    for ex in library:
        if q in (exercise_key(ex), str(ex.get("code"))):
            return ex
    matches = [ex for ex in library if str(ex.get("label", "")).casefold() == q.casefold()]
    if len(matches) == 1:
        return matches[0]
    raise WorkoutError("unknown_exercise")


def recent_keys(workouts: list[dict[str, Any]]) -> list[str]:
    """Zuletzt trainierte Übungen (neueste zuerst, ohne Duplikate)."""
    seen: dict[str, str] = {}
    for w in workouts or []:
        for e in w.get("exercises") or []:
            key = f"{e.get('libraryCode')}:{e.get('exerciseCode')}"
            at = e.get("completedAt") or w.get("completedAt") or ""
            if at > seen.get(key, ""):
                seen[key] = at
    return sorted(seen, key=seen.get, reverse=True)


def summary(ex: dict[str, Any], sets: list[dict[str, Any]], values: dict[str, Any]) -> str:
    """Kurzbeschreibung, sprachneutral (z. B. "Bankdrücken: 3 × 10 × 40 kg")."""
    parts: list[str] = []
    for s in sets:
        if s.get("reps"):
            part = f"{int(s['reps'])}"
        else:
            part = _fmt_duration(s.get("duration") or 0)
        if s.get("weight"):
            part += f" × {float(s['weight']):g} kg"
        parts.append(part)
    if values.get("duration"):
        parts.append(_fmt_duration(values["duration"]))
    if values.get("distance"):
        parts.append(f"{float(values['distance']):g} km")
    if values.get("calories"):
        parts.append(f"{int(values['calories'])} kcal")
    # aufeinanderfolgende gleiche Sätze zusammenfassen:
    # "10 × 40 kg, 10 × 40 kg, 8 × 45 kg" -> "2 × 10 × 40 kg, 8 × 45 kg"
    grouped = []
    for part, group in groupby(parts):
        count = len(list(group))
        grouped.append(f"{count} × {part}" if count > 1 else part)
    return f"{ex.get('label')}: {', '.join(grouped)}"


def _fmt_duration(seconds: int) -> str:
    seconds = int(seconds)
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d} min"

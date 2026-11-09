"""More than one charger (two KEBA boxes, say) - each car planned on its own, all within the main fuse.

Charger 1 is the one set up as before (its sensors under "What you have", its buttons on the car card); the others
live in settings["chargers"]: sensors, charger power, and the car's own "charge now", "ready at" and "at most".
Each extra charger is a part of its own (car2, car3 …): it starts in shadow and is put in control by itself.
Charger 1 comes first: the sun's surplus and the room under the main fuse go to it, the others are turned down first.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

POWER_WORDS = ("charging_power", "charge_power", "charger_power", "wallbox_power", "ladeeffekt")
PLUG_WORDS = ("plugged", "plug", "cable", "stik")
SESSION_WORDS = ("session_energy", "energy_session", "session")


def extras(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """The extra chargers that are set up (with a power or a plug sensor)."""
    return [c for c in (settings.get("chargers") or []) if isinstance(c, dict) and (c.get("power") or c.get("plug"))]


def _num(s: dict[str, Any] | None) -> float | None:
    try:
        return float((s or {}).get("state"))
    except (TypeError, ValueError):
        return None


def read(states: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    """One extra charger now: power (W), plugged in, charged this session (kWh)."""
    w = _num(states.get(c["power"])) if c.get("power") else None
    if w is not None and str(((states.get(c["power"]) or {}).get("attributes") or {}).get("unit_of_measurement") or "").lower() == "kw":
        w *= 1000
    plug = (states.get(c["plug"]) or {}).get("state") == "on" if c.get("plug") else (w or 0) > 100
    return {"name": c.get("name") or "", "power": w, "plug": plug,
            "session_kwh": _num(states.get(c["session"])) if c.get("session") else None}


def ready_at(c: dict[str, Any], now: datetime) -> datetime | None:
    if not c.get("ready"):
        return None
    hh, mm = (int(x) for x in str(c["ready"]).split(":")[:2])
    t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return t if t > now else t + timedelta(days=1)


def _template(obj: str, words: tuple[str, ...]) -> str | None:
    """The name with the role word cut out: keba_p30_charging_power_2 -> keba_p30_|_2 (tells two boxes apart)."""
    for w in words:
        if w in obj:
            return obj.replace(w, "|", 1)
    return None


def find(states: dict[str, Any], main_power: str | None, main_plug: str | None, taken: list[str],
         dismissed: list[str]) -> list[dict[str, Any]]:
    """Chargers in Home Assistant that aren't set up: a charging power sensor with a plug sensor of the same name."""
    plugs = {}
    sessions = {}
    for e, s in states.items():
        obj = e.split(".", 1)[1]
        if e.startswith("binary_sensor.") and (t := _template(obj, PLUG_WORDS)):
            plugs.setdefault(t, e)
        if e.startswith("sensor.") and (t := _template(obj, SESSION_WORDS)):
            sessions.setdefault(t, e)
    out = []
    for e, s in sorted(states.items()):
        if not e.startswith("sensor.") or e in (main_power,) or e in taken or e in dismissed:
            continue
        obj = e.split(".", 1)[1]
        t = _template(obj, POWER_WORDS)
        a = s.get("attributes") or {}
        if t is None or str(a.get("unit_of_measurement") or "").lower() not in ("w", "kw"):
            continue
        plug = plugs.get(t)
        if plug is None or plug == main_plug or plug in taken:
            continue  # a power sensor alone could be anything - a charger has a plug
        out.append({"power": e, "plug": plug, "session": sessions.get(t), "name": a.get("friendly_name") or e})
    return out

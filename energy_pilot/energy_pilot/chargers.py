"""More than one charger (two KEBA boxes, say) - each car planned on its own, all within the main fuse.

Charger 1 is the one set up as before (its sensors under "What you have", its buttons on the car card); the others
live in settings["chargers"]: sensors, charger power, and the car's own "charge now", "ready at" and "at most".
Each extra charger is a part of its own (car2, car3 …): it starts in shadow and is put in control by itself.
Charger 1 comes first: the sun's surplus and the room under the main fuse go to it, the others are turned down first.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import re
from typing import Any

POWER_WORDS = ("charging_power", "charge_power", "charger_power", "wallbox_power", "ladeeffekt")
PLUG_WORDS = ("plugged", "plug", "cable", "stik")
SESSION_WORDS = ("session_energy", "energy_session", "session")


# What a charger's plug sensor says when a car is in it - a binary sensor ("on") or an enum, like VEVOR's
# "plugged_in", OCPP's "Preparing"/"SuspendedEV" or go-e's "waiting".
_UNPLUGGED = ("off", "false", "available", "disconnected", "unplugged", "fault_unplugged", "not_connected", "no_car",
              "idle", "unavailable", "unknown", "none", "")


def is_plugged(state: Any) -> bool:
    s = str(state or "").strip().lower().replace(" ", "_")
    if s in _UNPLUGGED or "unplug" in s or "disconnect" in s or "not_connected" in s:
        return False
    return s in ("on", "true", "1") or any(w in s for w in (
        "plug", "connect", "charg", "wait", "paus", "suspend", "prepar", "finish", "complete", "occupied", "ready", "car"))


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
    plug = is_plugged((states.get(c["plug"]) or {}).get("state")) if c.get("plug") else (w or 0) > 100
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


# The switch that starts and stops a charger - only what has to do with charging is offered.
CHARGE_WORDS = re.compile(r"charg|evse|wallbox|(^|_)ev(_|$)|lader|ladebox|ladestation|laadpaal|laad|recharge|zappi|easee|"
                          r"keba|wallbox|go_?e|ohme|pod_?point|myenergi|commando")
_T = r"(?:^|_)"  # a whole word in entity_id style
NOT_CHARGER = re.compile(r"batter|inverter|discharg|grid_charg|ac_charg|force_charg|export|solar|backup|child|display|"
                         r"bornesikring|bornelas|barnlas|barnesikring|kinderslot|kindersicherung|securite_enfant|"
                         r"buzzer|firmware|restart|reboot|identify|sentry|climate|heater|defrost|steering|precondition|"
                         r"charge_port|cable_lock|" + _T + r"(sell|eco|lock|led|leds|light|lights|lys|screen|sound|beep|"
                         r"update|ota|sleep|seat|seats|valet|window|windows|door|doors|trunk|frunk)(?:_|$)")
CHARGER_MODEL = re.compile(r"charg|evse|wallbox|lader|laad|borne de|zappi|easee|keba|go-e|ohme|pod point", re.I)


def switch_options(registry: list[dict[str, Any]], devices: dict[str, dict[str, Any]], states: dict[str, Any],
                   anchors: list[str], skip_devices: set[str]) -> list[dict[str, Any]]:
    """Switches that can start and stop a charger: on a charger's own device, on the device that measures a
    charger's power (a Shelly, a smart plug), or named for charging - never the inverter's or the battery's."""
    by_id = {e["entity_id"]: e for e in registry}
    anchor_devs = {by_id[a]["device_id"] for a in anchors if a and (by_id.get(a) or {}).get("device_id")}
    current_devs = {e.get("device_id") for e in registry if e.get("device_id")
                    and re.match(r"(number|select)\..*(current|ampere|amp|courant|strom)", e["entity_id"])}
    out = []
    for e in registry:
        eid = e["entity_id"]
        if not eid.startswith("switch.") or e.get("disabled_by") or eid not in states:
            continue
        dev = e.get("device_id") or ""
        if dev and dev in skip_devices:
            continue
        name = str((states[eid].get("attributes") or {}).get("friendly_name") or eid)
        text = (eid.split(".", 1)[1] + " " + name.lower().replace(" ", "_"))
        if NOT_CHARGER.search(text):
            continue
        d = devices.get(dev) or {}
        model = " ".join(str(d.get(k) or "") for k in ("manufacturer", "model", "name", "name_by_user"))
        if dev in anchor_devs:
            why = "measures"
        elif CHARGE_WORDS.search(text):
            why = "name"
        elif dev and CHARGER_MODEL.search(model) and dev in current_devs:
            why = "charger"
        else:
            continue
        out.append({"entity_id": eid, "name": name, "device": dev, "why": why})
    order = {"measures": 0, "charger": 1, "name": 2}
    return sorted(out, key=lambda r: (order[r["why"]], r["name"].lower()))

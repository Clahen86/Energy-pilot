"""More than one home battery (a SolarEdge/BYD and a Victron, say).

The plan sees them as one battery - the capacities and powers added up, the level weighted by size. That keeps the
plan fast and is close to right; how the work is shared between them is the controller's job (shadow only for now).
Battery 1 is the one set up as before (its sensors under "What you have"); the others live in settings["batteries"].
"""

from __future__ import annotations

import re
from typing import Any

SOC_WORDS = ("state_of_charge", "state_of_energy", "battery_soc", "_soc", "battery_level")
NOT_A_HOME_BATTERY = ("phone", "iphone", "pixel", "ipad", "tablet", "watch", "laptop", "macbook", "car_", "_car", "tesla_model",
                      "vehicle", "ev_", "remote", "button", "sensor_battery", "mower", "vacuum", "roborock", "12v", "12_v")


def extras(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """The extra batteries that are set up (with at least a level sensor)."""
    return [b for b in (settings.get("batteries") or []) if isinstance(b, dict) and b.get("soc")]


def _num(s: dict[str, Any] | None) -> float | None:
    try:
        return float((s or {}).get("state"))
    except (TypeError, ValueError):
        return None


def _watts(s: dict[str, Any] | None) -> float | None:
    v = _num(s)
    if v is None:
        return None
    unit = str(((s or {}).get("attributes") or {}).get("unit_of_measurement") or "").lower()
    return v * 1000 if unit == "kw" else v


def read(states: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """One extra battery now: level (%), power (W, + = charging) and size."""
    w = _watts(states.get(b["power"])) if b.get("power") else None
    if w is not None and b.get("sign") == -1:
        w = -w
    return {"name": b.get("name") or "", "soc": _num(states.get(b["soc"])), "power": w, "kwh": float(b.get("kwh") or 10)}


def combine(main: dict[str, Any], others: list[dict[str, Any]]) -> tuple[float | None, float | None]:
    """The level weighted by size, the powers added up. A battery that can't be read leaves the level unknown."""
    all_ = [main] + others
    if any(x["soc"] is None for x in all_):
        soc = None
    else:
        total = sum(x["kwh"] for x in all_)
        soc = round(sum(x["soc"] * x["kwh"] for x in all_) / total, 1) if total else None
    ws = [x["power"] for x in all_ if x["power"] is not None]
    return soc, (sum(ws) if ws else None)


def _prefix(entity: str) -> str:
    obj = entity.split(".", 1)[1]
    for w in SOC_WORDS:
        if w in obj:
            return obj.split(w)[0].rstrip("_")
    return obj


def _device(entity: str) -> str:
    """The first word of the name - what usually tells one inverter or battery from another."""
    return re.split(r"[_.]", entity.split(".", 1)[1])[0]


def find(states: dict[str, Any], main_soc: str | None, taken: list[str], dismissed: list[str]) -> list[dict[str, Any]]:
    """Batteries in Home Assistant that aren't set up: a level sensor on another device than battery 1,
    with the battery power sensor beside it when there is one."""
    seen_devices = {_device(main_soc)} if main_soc else set()
    seen_devices |= {_device(e) for e in taken if e}
    out = []
    for e, s in sorted(states.items()):
        if not e.startswith("sensor.") or e in taken or e in dismissed or e == main_soc:
            continue
        a = s.get("attributes") or {}
        obj = e.split(".", 1)[1]
        if not any(w in obj for w in SOC_WORDS) or any(w in obj for w in NOT_A_HOME_BATTERY):
            continue
        if str(a.get("unit_of_measurement") or "") != "%" or a.get("device_class") not in ("battery", None):
            continue
        if _num(s) is None or _device(e) in seen_devices:
            continue
        pre = _prefix(e)
        power = None
        best = 0
        for p, ps in states.items():
            pa = ps.get("attributes") or {}
            if not p.startswith("sensor.") or "batter" not in p or _device(p) != _device(e):
                continue
            if str(pa.get("unit_of_measurement") or "").lower() not in ("w", "kw"):
                continue
            pobj = p.split(".", 1)[1]
            common = len(pre) if pobj.startswith(pre) else len(_device(e))
            if "power" in pobj and common > best:
                power, best = p, common
        if power is None and not any(w in obj for w in ("state_of_charge", "state_of_energy", "_soc")):
            continue  # "battery_level" without a battery power beside it: a phone or a tablet, not a home battery
        out.append({"soc": e, "power": power, "name": a.get("friendly_name") or e})
        seen_devices.add(_device(e))  # one battery per device
    return out

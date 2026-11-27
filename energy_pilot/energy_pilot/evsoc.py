"""The car's own battery level: charge to a target (80 % spares the battery), or 100 % for the next trip.

Two limits: from the grid up to the target, and with the sun's surplus up to its own (e.g. 80 % from the grid,
the last 20 % only when the sun gives it for free).

With the car's level known, what's missing is (target - level) x the car's battery size. The size is learned from the
charger: kWh put in against the % it rose (losses included). Without a level, the plan works on kWh as before.
"""

from __future__ import annotations

from statistics import median
from typing import Any

DEFAULT_TARGET = 80
DEFAULT_KWH = 60.0  # until it's learned or set - a middle-sized car
LOSS = 0.9  # what reaches the battery of what the charger gives
MIN_KWH = 4.0  # the smallest car battery learned: a plug-in hybrid has 8-20 kWh


def charger_kwh(states: dict[str, Any]) -> float | None:
    """The car's battery size as its charger knows it, before Energy Pilot has learned it: evcc's vehicle at the
    loadpoint (its "Vehicle" select carries the car's capacity), else evcc's one vehicle_capacity sensor."""
    for e, st in states.items():
        if e.startswith("select.") and e.endswith("_vehicle_name"):
            v = ((st or {}).get("attributes") or {}).get("vehicle") or {}
            try:
                c = float(v.get("capacity") or (v.get("originObject") or {}).get("capacity"))
            except (TypeError, ValueError):
                continue
            if 2 <= c <= 220:
                return c
    caps = []
    for e, st in states.items():
        if e.startswith("sensor.") and e.endswith("_vehicle_capacity"):
            unit = str(((st or {}).get("attributes") or {}).get("unit_of_measurement") or "kWh").lower()
            try:
                c = float((st or {}).get("state"))
            except (TypeError, ValueError):
                continue
            if unit == "kwh" and 2 <= c <= 220:
                caps.append(c)
    return caps[0] if len(caps) == 1 else None  # more cars and none at the loadpoint: no telling which


def target(settings: dict[str, Any]) -> int:
    """100 % when the next trip is long, else the everyday target."""
    if settings.get("ev_trip"):
        return 100
    try:
        return max(20, min(100, int(settings.get("ev_target") or DEFAULT_TARGET)))
    except (TypeError, ValueError):
        return DEFAULT_TARGET


def sun_target(settings: dict[str, Any]) -> int:
    """How far the sun's surplus may fill the car - never below the grid target (the same when not set)."""
    grid = target(settings)
    v = settings.get("ev_sun_target")
    try:
        return max(grid, min(100, int(v))) if v else grid
    except (TypeError, ValueError):
        return grid


def charger_kw(settings: dict[str, Any], learned: float | None) -> float:
    """The power the plan counts on for the car: the charger's as set (7.4 kW if not), but never more than the car
    was seen to take - the plan would put the charge in too few hours."""
    try:
        kw = float(settings.get("charger_kw") or 0)
    except (TypeError, ValueError):
        kw = 0.0
    if learned:
        return min(kw, learned) if kw else learned
    return kw or 7.4


def need_kwh(soc: float, goal: float, car_kwh: float) -> float:
    """What the charger must give to bring the car from soc to goal."""
    return max(0.0, goal - soc) / 100 * car_kwh / LOSS


def num(state: dict[str, Any] | None) -> float | None:
    try:
        v = float((state or {}).get("state"))
    except (TypeError, ValueError):
        return None
    return v if 0 <= v <= 100 else None


class CarSize:
    """The car's battery size, learned: during a charge, kWh from the charger against the rise in %."""

    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state
        self._start: tuple[float, float] | None = None  # soc, session kWh when this charge began
        self._kw: list[float] = []  # this session's charging power (kW), one a minute

    def see(self, plug: bool | None, soc: float | None, session_kwh: float | None, power_w: float | None = None) -> None:
        self._see_power(plug, power_w)
        if not plug or soc is None or session_kwh is None:
            self._start = None
            return
        if self._start is None or session_kwh < self._start[1] - 0.5:  # a new session
            self._start = (soc, session_kwh)
            return
        s0, k0 = self._start
        if soc - s0 >= 15 and session_kwh - k0 >= 3:
            size = (session_kwh - k0) * LOSS / (soc - s0) * 100
            if MIN_KWH <= size <= 220:
                seen = (self.state.setdefault("ev_kwh_seen", []) + [round(size, 1)])[-6:]
                self.state["ev_kwh_seen"] = seen
            self._start = (soc, session_kwh)

    def _see_power(self, plug: bool | None, power_w: float | None) -> None:
        """What the car really takes: a car charging on one phase behind an 11 kW charger takes 3.7 kW. While it
        charges (over 1 kW) the power is kept a minute at a time; when the car is unplugged, a session of at least
        10 minutes gives its 90th percentile - the steady power, not the start or the taper near full."""
        if plug and power_w is not None and power_w >= 1000:
            self._kw.append(power_w / 1000)
            return
        if plug:
            return  # paused (the plan waits, or the sun is gone): the same session goes on
        if len(self._kw) >= 10:
            k = sorted(self._kw)[int(0.9 * (len(self._kw) - 1))]
            self.state["ev_kw_seen"] = (self.state.get("ev_kw_seen") or [])[-5:] + [round(k, 1)]
        self._kw = []

    def charge_kw(self) -> float | None:
        """The most the car took in its last sessions (a session charged by the sun alone takes less)."""
        seen = self.state.get("ev_kw_seen") or []
        return max(seen) if seen else None

    def kwh(self, settings: dict[str, Any]) -> tuple[float, str]:
        """(kWh, "set" | "learned" | "guess")."""
        try:
            if settings.get("ev_battery_kwh"):
                return float(settings["ev_battery_kwh"]), "set"
        except (TypeError, ValueError):
            pass
        seen = self.state.get("ev_kwh_seen") or []
        if len(seen) >= 2:
            return round(median(seen), 1), "learned"
        return DEFAULT_KWH, "guess"


def trip_done(settings: dict[str, Any], plug: bool | None, was_plugged: bool, soc: float | None) -> bool:
    """The trip button goes off by itself when the car leaves full (unplugged at 95 % or more)."""
    return bool(settings.get("ev_trip")) and was_plugged and not plug and (soc is None or soc >= 95)


def unplugged(state: Any) -> bool:
    """The plug sensor says the car is out - not merely unavailable or unknown for a moment."""
    from .chargers import is_plugged

    s = str(state or "").strip().lower()
    return s not in ("", "unavailable", "unknown", "none") and not is_plugged(state)


async def end_charge_now(ov: Any, ha: Any, was: bool, was_extra: dict[int, bool]) -> None:
    """"Charge now" is for one charge: off when the car is unplugged, so the next plug-in follows the plan again."""
    from .chargers import extras

    st, states = ov.settings, ha.states
    pe = ov.role("ev_plug")
    if was and pe and unplugged((states.get(pe) or {}).get("state")):
        me = ov.role("ev_manual")
        if me:
            if (states.get(me) or {}).get("state") == "on":
                await ha.call_service(me.split(".")[0], "turn_off", {"entity_id": me})
        elif st.get("ev_now"):
            ov.save({"ev_now": False})
    conf, changed = list(st.get("chargers") or []), False
    for i, c in enumerate(extras(st)):
        if c.get("now") and was_extra.get(i) and c.get("plug") and unplugged((states.get(c["plug"]) or {}).get("state")):
            conf[conf.index(c)] = {**c, "now": False}
            changed = True
    if changed:
        ov.save({"chargers": conf})

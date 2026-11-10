"""The car's own battery level: charge to a target (80 % spares the battery), or 100 % for the next trip.

With the car's level known, what's missing is (target - level) x the car's battery size. The size is learned from the
charger: kWh put in against the % it rose (losses included). Without a level, the plan works on kWh as before.
"""

from __future__ import annotations

from statistics import median
from typing import Any

DEFAULT_TARGET = 80
DEFAULT_KWH = 60.0  # until it's learned or set - a middle-sized car
LOSS = 0.9  # what reaches the battery of what the charger gives


def target(settings: dict[str, Any]) -> int:
    """100 % when the next trip is long, else the everyday target."""
    if settings.get("ev_trip"):
        return 100
    try:
        return max(20, min(100, int(settings.get("ev_target") or DEFAULT_TARGET)))
    except (TypeError, ValueError):
        return DEFAULT_TARGET


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

    def see(self, plug: bool | None, soc: float | None, session_kwh: float | None) -> None:
        if not plug or soc is None or session_kwh is None:
            self._start = None
            return
        if self._start is None or session_kwh < self._start[1] - 0.5:  # a new session
            self._start = (soc, session_kwh)
            return
        s0, k0 = self._start
        if soc - s0 >= 15 and session_kwh - k0 >= 3:
            size = (session_kwh - k0) * LOSS / (soc - s0) * 100
            if 10 <= size <= 220:
                seen = (self.state.setdefault("ev_kwh_seen", []) + [round(size, 1)])[-6:]
                self.state["ev_kwh_seen"] = seen
            self._start = (soc, session_kwh)

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

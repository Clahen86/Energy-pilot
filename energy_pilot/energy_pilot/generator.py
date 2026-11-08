"""Off-grid: when the generator should run - from the battery, the sun and the house's use ahead.

No grid and no prices: the battery is all there is, and the generator fills it. It runs:
- always when the battery falls to the emergency level (whatever the plan or the quiet hours)
- before the battery would fall below the reserve: the forecast (sun and house, hour by hour) is played forward,
  and the generator starts so late that it can still fill what's missing in time - not at all if the sun will do it
- in long runs, not many short ones: once started it runs at least its minimum time, then stops when the battery is
  full enough, or when the sun ahead will carry it to the next day
- not in the quiet hours (night) unless the battery would otherwise run dry before they end
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from typing import Any


@dataclass
class GenSettings:
    capacity_kwh: float = 30.0
    efficiency: float = 0.92  # round trip
    reserve_soc: float = 30.0  # the plan never goes below this
    emergency_soc: float = 20.0  # start at once, always
    stop_soc: float = 90.0  # a run fills to this
    charge_kw: float = 5.0  # what the inverter's charger can take from the generator
    min_run_h: float = 2.0
    quiet: frozenset = frozenset()  # hours (0-23) the generator should rest


def simulate(soc: float, hours: list[tuple[datetime, float, float]], s: GenSettings) -> list[tuple[datetime, float]]:
    """The battery level hour by hour without the generator: (start, soc at the end of the hour).
    hours: (start, house kWh, sun kWh)."""
    out, kwh = [], soc / 100 * s.capacity_kwh
    eff = math.sqrt(s.efficiency)
    for t, house, sun in hours:
        net = sun - house
        kwh += net * eff if net > 0 else net / eff
        kwh = max(0.0, min(s.capacity_kwh, kwh))
        out.append((t, kwh / s.capacity_kwh * 100))
    return out


def decide(now: datetime, soc: float | None, running: bool, running_since: datetime | None,
           hours: list[tuple[datetime, float, float]], s: GenSettings) -> dict[str, Any]:
    """{"run": bool, "why": str, "low_at": iso | None, "start_at": iso | None, "need_kwh": float}."""
    if soc is None:
        return {"run": running, "why": "no_soc", "low_at": None, "start_at": None, "need_kwh": 0.0}
    ran_h = (now - running_since).total_seconds() / 3600 if running and running_since else 0.0
    path = simulate(soc, hours, s)
    low = next(((t, v) for t, v in path if v < s.reserve_soc), None)
    need = 0.0
    if low:
        # What it takes to stay at the reserve through the lowest point ahead (within the forecast).
        lowest = min(v for _t, v in path)
        need = max(0.0, (s.reserve_soc - lowest) / 100 * s.capacity_kwh)
    base = {"low_at": low[0].isoformat() if low else None, "need_kwh": round(need, 1)}

    if running:
        if ran_h < s.min_run_h:
            return {"run": True, "why": "min_run", "start_at": None, **base}
        if soc >= s.stop_soc:
            return {"run": False, "why": "full", "start_at": None, **base}
        if not low:
            return {"run": False, "why": "sun_carries", "start_at": None, **base}  # the sun ahead does the rest
        return {"run": True, "why": "filling", "start_at": None, **base}

    if soc <= s.emergency_soc:
        return {"run": True, "why": "emergency", "start_at": now.isoformat(), **base}
    if not low:
        return {"run": False, "why": "not_needed", "start_at": None, **base}
    # Fill from the reserve point back to the stop level, in a run of at least the minimum time.
    fill_kwh = need + (s.stop_soc - s.reserve_soc) / 100 * s.capacity_kwh
    run_h = max(s.min_run_h, fill_kwh / max(0.5, s.charge_kw))
    start = low[0] - timedelta(hours=math.ceil(run_h))
    # Not in the quiet hours: start before them if the battery would run low during them.
    while start.hour in s.quiet and start > now:
        start -= timedelta(hours=1)
    if now >= start:
        quiet_now = now.hour in s.quiet
        if quiet_now and low[0] > now + timedelta(hours=_hours_left_in_quiet(now, s.quiet)):
            return {"run": False, "why": "quiet", "start_at": None, **base}  # it can wait until the quiet hours end
        return {"run": True, "why": "before_low", "start_at": start.isoformat(), **base}
    return {"run": False, "why": "later", "start_at": start.isoformat(), **base}


def _hours_left_in_quiet(now: datetime, quiet: frozenset) -> int:
    h, n = now.hour, 0
    while (h + n) % 24 in quiet and n < 24:
        n += 1
    return n

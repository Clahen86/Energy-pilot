"""What Energy Pilot would have saved last month - worked out on the first day from the house's own history, so a new
user sees what it's worth before weeks of shadow have measured it.

Each past day is run twice on the same house use, sun and prices: once with the battery left to itself (the inverter's
own way: the sun's surplus in, the house's need out, never from the grid) and once with Energy Pilot's plan. The plan
knew the whole day in advance - more than it ever will - so the difference is taken down by a fifth, and called
"about". Only with at least a week of history, and only days where every hour is known.
"""

from __future__ import annotations

from datetime import date, datetime
import math
from statistics import median
from typing import Any

MIN_DAYS = 7
FORESIGHT = 0.8  # the plan saw each day whole: a fifth off for what a forecast wouldn't have known
SHOW_DAYS = 14  # shown while the own measuring is younger than this


def selfuse(hours: list[Any], b: Any) -> tuple[float, float]:
    """The battery on its own through the hours (starting empty): (cost, kWh left at the end)."""
    half = math.sqrt(max(0.5, b.efficiency))
    floor = b.capacity_kwh * b.min_soc / 100
    top = b.capacity_kwh * b.max_soc / 100
    kwh, cost = floor, 0.0
    for h in hours:
        need = h.house - h.sun
        if need < 0:  # the sun's surplus: into the battery as far as it takes, the rest sold
            take = min(-need, b.max_charge_kw * h.length, max(0.0, (top - kwh) / half))
            kwh += take * half
            grid = need + take
        else:
            give = min(need, b.max_discharge_kw * h.length, max(0.0, (kwh - floor) * half))
            kwh -= give / half
            grid = need - give
        cost += grid * h.price if grid > 0 else grid * h.sell
    return cost, kwh - floor


def estimate(days: dict[date, list[Any]], b: Any) -> dict[str, Any] | None:
    """{"per_month", "days"}: what the plan would have saved against the battery on its own, per 30 days."""
    from .engine import plan_battery

    total, n = 0.0, 0
    for _day, hours in sorted(days.items()):
        if len(hours) < 23:
            continue  # a day with hours missing: left out rather than guessed
        worth = median(h.price for h in hours) * math.sqrt(b.efficiency)  # what a kWh left over is worth later
        own_cost, own_left = selfuse(hours, b)
        plan = plan_battery(hours, b.min_soc, b, end_value=worth)
        if not plan.steps:
            continue
        plan_left = (plan.steps[-1].soc_end - b.min_soc) / 100 * b.capacity_kwh
        total += (own_cost - own_left * worth) - (plan.cost - plan_left * worth)
        n += 1
    if n < MIN_DAYS:
        return None
    return {"per_month": round(max(0.0, total / n * 30 * FORESIGHT), 0), "days": n}


def build(house: list[tuple[datetime, float]], sun: dict[datetime, float], prices: dict[datetime, float],
          sell: float) -> dict[date, list[Any]]:
    """Hourly house use (kW), sun (kW) and prices into days of Hours - only hours where all three are known."""
    from .engine import Hour

    out: dict[date, list[Any]] = {}
    for t, kw in sorted(house):
        if t not in prices:
            continue
        out.setdefault(t.date(), []).append(Hour(t, prices[t], sell, max(0.0, kw), max(0.0, sun.get(t, 0.0))))
    return out

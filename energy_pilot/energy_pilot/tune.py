"""Its own settings, tested every night on the house's own days.

Two inner knobs decide a lot: what a kWh left in the battery at the end of the plan is worth (the end value) and the
margin kept on the house's use in the dear hours. Both have learners of their own in learning.py; this sits on top of
them as a small adjustment, found by replaying the last two weeks:

- every hour of each day, the planner plans the rest of the day from what was forecast then, and its first step is
  carried out against what really happened (the same way as the nightly "Prøvekørsel" on GitHub)
- that is done with the settings in use now, a step either way on each knob, and with no adjustment at all
- it moves one small step only when the other setting would clearly have cost less: over at least five days, by at
  least half a per cent, and better on most of the days where they differ - and back to no adjustment the same way
  if that turns out best

Nothing outside the bounds, never more than a step a night, and it can be switched off (then nothing is adjusted).
"""
from __future__ import annotations

from datetime import datetime, timedelta
import math
from typing import Any

from .engine import Battery, Hour, end_price, plan_battery

F_STEP, M_STEP = 0.05, 0.05
F_MIN, F_MAX = 0.8, 1.25
M_MIN, M_MAX = -0.15, 0.3
MIN_DAYS = 5
MIN_GAIN = 0.005  # share of the cost
KEEP_DAYS = 14
T0 = datetime(2026, 1, 1)


def step(action: str, soc: float, target: float, house: float, sun: float, b: Battery) -> tuple[float, float]:
    """One hour carried out against what really happened: (level after, grid kWh: + bought, - sold)."""
    half, cap = math.sqrt(b.efficiency), b.capacity_kwh
    kwh, floor = soc / 100 * cap, b.min_soc / 100 * cap
    need = house - sun
    batt = 0.0
    if need < 0:  # sun left over: into the battery as far as it takes
        batt = min(-need, b.max_charge_kw, max(0.0, (cap - kwh) / half))
    if action == "charge_grid":
        batt = max(batt, min(max(0.0, (target / 100 * cap - kwh) / half), b.max_charge_kw))
    elif action == "discharge" and need > 0:
        batt = -min(need, b.max_discharge_kw, max(0.0, (kwh - floor) * half))
    kwh += batt * half if batt > 0 else batt / half
    return max(0.0, min(100.0, kwh / cap * 100)), need + batt


def usable(rows: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    rows = sorted((r for r in rows if r.get("price") is not None), key=lambda r: r["h"])
    if len(rows) < 20 or rows[0]["soc"][1] is None:
        return None
    if any(r["house"][1] is None or not 0 <= r["house"][1] <= 30 for r in rows):
        return None
    if len({round(r["house"][1], 3) for r in rows}) <= 2:
        return None  # a sensor stuck on one value
    return rows


def replay(rows: list[dict[str, Any]], b: Battery, sell: float, end_factor: float, margin: float) -> float:
    """What the grid would have cost that day with these settings - less what the battery holds more at the end than
    at the start, at what refilling it costs (else the setting that empties the battery always looks cheapest)."""
    real = [(r["house"][1], r["sun"][1] or 0.0) for r in rows]
    exp = [(r["house"][0] if r["house"][0] is not None else r["house"][1],
            r["sun"][0] if r["sun"][0] is not None else (r["sun"][1] or 0.0)) for r in rows]
    price = [float(r["price"]) for r in rows]
    soc, cost = float(rows[0]["soc"][1]), 0.0
    start = soc
    for i in range(len(rows)):
        ahead = price[i:]
        dear = sorted(ahead)[int(len(ahead) * 0.75)] if len(ahead) > 3 else None
        hours = [Hour(T0 + timedelta(hours=rows[j]["h"]), price[j], sell,
                      max(0.0, exp[j][0] + (margin if dear is not None and price[j] >= dear else 0.0)), exp[j][1])
                 for j in range(i, len(rows))]
        hours[0].house, hours[0].sun = real[i]  # the hour now is seen as it goes
        plan = plan_battery(hours, soc, b, end_value=end_price(hours, b) * end_factor)
        first = plan.steps[0] if plan.steps else None
        soc, grid = step(first.action if first else "discharge", soc, first.soc_end if first else 0, real[i][0], real[i][1], b)
        cost += grid * price[i] if grid > 0 else grid * sell
    day = [Hour(T0 + timedelta(hours=r["h"]), p, sell, 0.0, 0.0) for r, p in zip(rows, price)]
    return cost - (soc - start) / 100 * b.capacity_kwh * end_price(day, b)


def _clip(f: float, m: float, base_margin: float) -> tuple[float, float]:
    f = round(min(F_MAX, max(F_MIN, f)), 2)
    m = round(min(M_MAX, max(M_MIN, m, -base_margin)), 2)  # the margin in all never below nothing
    return f, m


def nightly(state: dict[str, Any], b: Battery, sell: float, base_end: float, base_margin: float, today: str) -> dict[str, Any]:
    """Test the settings on the kept days and move a step if another clearly did better. Changes state["tune"]."""
    t = state.setdefault("tune", {"f": 1.0, "m": 0.0, "log": []})
    days = [r for r in (usable(v) for _, v in sorted((state.get("recent") or {}).items())) if r]
    t["days"] = len(days)
    if len(days) < MIN_DAYS or b.capacity_kwh <= 0:
        return t
    cur = (t["f"], t["m"])
    cands = {cur, _clip(1.0, 0.0, base_margin)}
    for df, dm in ((F_STEP, 0), (-F_STEP, 0), (0, M_STEP), (0, -M_STEP)):
        cands.add(_clip(cur[0] + df, cur[1] + dm, base_margin))
    costs = {c: [replay(d, b, sell, base_end * c[0], base_margin + c[1]) for d in days] for c in cands}
    total = {c: sum(v) for c, v in costs.items()}
    best = min(cands, key=lambda c: (round(total[c], 6), c != cur))
    t["tested"] = today
    if best == cur:
        return t
    gain = total[cur] - total[best]
    scale = max(sum(abs(x) for x in costs[cur]), 1e-6)  # the days' costs, each counted as its size (selling can net to 0)
    differ = [(a, c) for a, c in zip(costs[cur], costs[best]) if abs(a - c) > 1e-6]
    wins = sum(1 for a, c in differ if c < a)
    if gain / scale < MIN_GAIN or not differ or wins * 10 < len(differ) * 6:
        return t  # not clearly better: stays as it is
    t["f"], t["m"] = best
    t["log"] = (t.get("log") or [])[-9:] + [{"d": today, "f": best[0], "m": best[1], "from": list(cur),
                                             "gain": round(gain, 2), "pct": round(100 * gain / scale, 1), "days": len(days)}]
    return t


def seed(t: dict[str, Any], start: dict[str, Any] | None) -> dict[str, Any]:
    """Before its own test has run: start from houses like this one (common.tune_start) - or back to the standard if
    that start is gone (switched off, or the houses no longer agree). Once tested on its own days, it's left alone."""
    if t.get("log") or int(t.get("days") or 0) >= MIN_DAYS:
        return t
    if start:
        t.update(f=start["f"], m=start["m"], start=start["n"])
    elif t.pop("start", None):
        t.update(f=1.0, m=0.0)
    return t


def keep(state: dict[str, Any], day: str, rows: list[dict[str, Any]]) -> None:
    """The day's hours (plan and real) for the nightly test - two weeks kept."""
    recent = dict(state.get("recent") or {})
    recent[day] = rows
    state["recent"] = {k: recent[k] for k in sorted(recent)[-KEEP_DAYS:]}


def info(state: dict[str, Any], on: bool) -> dict[str, Any]:
    t = state.get("tune") or {}
    log = t.get("log") or []
    return {"on": on, "f": t.get("f", 1.0), "m": t.get("m", 0.0), "days": t.get("days", 0), "need": MIN_DAYS,
            "last": log[-1] if log else None, "start": t.get("start")}

"""Replay real days with one version of Energy Pilot's planner.

Each day of each home: every hour the planner plans the rest of the day from what was forecast then (the house's use
and the sun), and its first step is carried out against what really happened. What the grid cost is added up - and
set against the same battery left to itself (house first, sun only) and against no battery at all.

    PYTHONPATH=<checkout>/energy_pilot python training/backtest.py data.json > result.json
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import math
import sys

from energy_pilot.engine import Battery, Hour, end_price, plan_battery

T0 = datetime(2026, 1, 1)


def battery_for(kind: dict) -> Battery:
    cap = float(kind.get("battery_kwh") or 10.0)
    kw = max(1.0, min(5.0, cap / 3))  # unknown: about a third of the capacity per hour
    return Battery(capacity_kwh=cap, max_charge_kw=kw, max_discharge_kw=kw, min_soc=10.0, efficiency=0.9)


def step(action: str, soc: float, target: float, house: float, sun: float, b: Battery) -> tuple[float, float]:
    """One hour carried out against reality: (soc after, grid kWh: + bought, - sold)."""
    half, cap = math.sqrt(b.efficiency), b.capacity_kwh
    kwh, floor, top = soc / 100 * cap, b.min_soc / 100 * cap, cap
    need = house - sun
    batt = 0.0  # + into the battery (kWh at the terminals), - out
    if need < 0:  # sun left over: always into the battery as far as it takes
        batt = min(-need, b.max_charge_kw, max(0.0, (top - kwh) / half))
    if action == "charge_grid":
        want = max(0.0, (target / 100 * cap - kwh) / half)
        batt = max(batt, min(want, b.max_charge_kw))
    elif action == "discharge" and need > 0:
        batt = -min(need, b.max_discharge_kw, max(0.0, (kwh - floor) * half))
    kwh += batt * half if batt > 0 else batt / half
    return kwh / cap * 100, need + batt


def selfuse(soc: float, house: float, sun: float, b: Battery) -> tuple[float, float]:
    return step("discharge", soc, 0, house, sun, b)


def replay(day: dict, end_factor: float = 1.0, margin: float = 0.0) -> dict | None:
    rows = sorted((r for r in day.get("hours") or [] if r.get("price") is not None), key=lambda r: r["h"])
    real = [(r["house"][1], r["sun"][1]) for r in rows]
    if len(rows) < 20 or any(h is None for h, _ in real) or rows[0]["soc"][1] is None:
        return None
    if any(h < 0 or h > 30 for h, _ in real) or len({round(h, 3) for h, _ in real}) <= 2:
        return None  # the sensor guard (train.plausible_day): numbers that can't be right stay out
    b = battery_for(day.get("kind") or {})
    exp = [((r["house"][0] if r["house"][0] is not None else r["house"][1]), (r["sun"][0] if r["sun"][0] is not None else (r["sun"][1] or 0.0)))
           for r in rows]
    price = [float(r["price"]) for r in rows]
    soc = soc_s = float(rows[0]["soc"][1])
    cost = cost_s = cost_n = 0.0
    for i, r in enumerate(rows):
        dear = sorted(price[i:])[int(len(price[i:]) * 0.75)] if len(price[i:]) > 3 else None
        hours = [Hour(T0 + timedelta(hours=r2["h"]), price[j], 0.0, exp[j][0] + (margin if dear is not None and price[j] >= dear else 0.0), exp[j][1])
                 for j, r2 in enumerate(rows) if j >= i]
        hours[0].house, hours[0].sun = real[i][0], real[i][1] or 0.0  # the hour now is seen as it goes
        plan = plan_battery(hours, soc, b, end_value=end_price(hours, b) * end_factor)
        first = plan.steps[0] if plan.steps else None
        house, sun = real[i][0], real[i][1] or 0.0
        soc, grid = step(first.action if first else "discharge", soc, first.soc_end if first else 0, house, sun, b)
        soc_s, grid_s = selfuse(soc_s, house, sun, b)
        cost += max(0.0, grid) * price[i]
        cost_s += max(0.0, grid_s) * price[i]
        cost_n += max(0.0, house - sun) * price[i]
    return {"cost": cost, "selfuse": cost_s, "none": cost_n, "country": (day.get("kind") or {}).get("country")}


def tune(data: list[dict]) -> None:
    """The best settings: the same days replayed with Energy Pilot's two inner knobs turned - how much the battery's
    rest is worth at the end of the plan (end factor) and the margin kept for the dear hours. Markdown, totals only;
    nothing is changed by it - a person decides whether a default should move."""
    import random

    random.seed(7)
    days = data if len(data) <= 120 else random.sample(data, 120)
    results = []
    for f in (0.75, 0.9, 1.0, 1.1, 1.25):
        for m in (0.0, 0.1, 0.2):
            out = [x for x in (replay(d, f, m) for d in days) if x]
            if out:
                results.append((sum(x["selfuse"] - x["cost"] for x in out), f, m, len(out)))
    print("## Bedste indstillinger\n")
    if not results:
        print("Ingen hele dage endnu.")
        return
    results.sort(reverse=True)
    base = next((r for r in results if r[1] == 1.0 and r[2] == 0.0), results[-1])
    print("| Slutværdi | Margin | Energipilots egen andel | Mod standard |\n|---|---|---|---|")
    for g, f, m, n in results[:6]:
        print(f"| {f} | {m} kWh | {g:.0f} | {g - base[0]:+.0f} |")
    print(f"\n{results[0][3]} dage. Standard i dag er slutværdi 1.0 og margin 0 (den lærte margin pr. hus kommer oveni).")


def main() -> None:
    if len(sys.argv) > 2 and sys.argv[2] == "--tune":
        tune(json.load(open(sys.argv[1])))
        return
    data = json.load(open(sys.argv[1]))
    out = [x for x in (replay(d) for d in data) if x]
    json.dump({"days": len(out), "homes": len({d["home"] for d in data}),
               "cost": round(sum(x["cost"] for x in out), 2), "selfuse": round(sum(x["selfuse"] for x in out), 2),
               "none": round(sum(x["none"] for x in out), 2),
               "by_country": {c: round(sum(x["selfuse"] - x["cost"] for x in out if x["country"] == c), 2)
                              for c in sorted({x["country"] or "?" for x in out})}}, sys.stdout)


if __name__ == "__main__":
    main()

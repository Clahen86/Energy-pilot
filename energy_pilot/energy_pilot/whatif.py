"""What if: the last 30 days replayed with a bigger battery or more panels - the same plan, the same prices, the same
house. Measured on the house's own hours, kept small on disk. Once a day, in the background; shown when 7 days are in."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import json
import math
from pathlib import Path
from statistics import median
from typing import Any

KEEP_H = 30 * 24
MIN_DAYS = 7
MORE_KWH = 5.0  # "a bigger battery": this much more
MORE_SUN = 1.3  # "more panels": 30 % more sun


class Hourly:
    """The house's hours: average house use, sun, price and feed-in price - from the rounds every 5 minutes."""

    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            self.h: dict[str, dict[str, float]] = json.loads(path.read_text())
        except (OSError, ValueError):
            self.h = {}
        self._dirty = 0

    def add(self, now: datetime, house_w: float | None, pv_w: float | None, price: float | None, sell: float | None) -> None:
        if house_w is None or price is None:
            return
        key = now.strftime("%Y-%m-%dT%H")
        r = self.h.setdefault(key, {"n": 0, "house": 0.0, "sun": 0.0, "price": 0.0, "sell": 0.0})
        n = r["n"]
        for k, v in (("house", max(0.0, house_w) / 1000), ("sun", max(0.0, pv_w or 0.0) / 1000), ("price", price), ("sell", sell or 0.0)):
            r[k] = round((r[k] * n + v) / (n + 1), 4)  # a running average: kW over the hour = kWh
        r["n"] = n + 1
        for k in sorted(self.h)[:-KEEP_H]:
            self.h.pop(k)
        self._dirty += 1
        if self._dirty >= 12:
            self.save()

    def save(self) -> None:
        self._dirty = 0
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.h, separators=(",", ":")))
            tmp.replace(self.path)
        except OSError:
            pass

    def days(self, today: str) -> list[list[tuple[str, dict[str, float]]]]:
        """Whole days seen (at least 20 hours), not today."""
        by: dict[str, list] = {}
        for k, r in sorted(self.h.items()):
            if k[:10] < today and r.get("n", 0) >= 3:
                by.setdefault(k[:10], []).append((k, r))
        return [v for v in by.values() if len(v) >= 20]


def compute(days: list, b: Any, tz: Any) -> dict[str, Any] | None:
    """Cost per month now, with a bigger battery, with more panels and with no battery."""
    from .engine import Hour, plan_battery

    if len(days) < MIN_DAYS:
        return None
    bigger = replace(b, capacity_kwh=b.capacity_kwh + MORE_KWH, force={}, targets=(), at=())
    plain = replace(b, force={}, targets=(), at=())
    # All the days in one run, as the battery really goes from one day into the next. It starts empty; what is
    # left at the very end counts at what it is worth later.
    hours = [Hour(datetime.fromisoformat(k + ":00").replace(tzinfo=tz), r["price"], r["sell"], r["house"], r["sun"])
             for day in days for k, r in day]
    end = median(h.price for h in hours) * math.sqrt(b.efficiency)

    step_kwh = 0.02 * b.capacity_kwh  # the same steps in kWh for both sizes - else rounding favours one of them

    def net(hs: list, bb: Any) -> tuple[float, float]:
        p = plan_battery(hs, bb.min_soc, bb, end_value=end, step_pct=100 * step_kwh / bb.capacity_kwh)
        left = ((p.steps[-1].soc_end if p.steps else bb.min_soc) - bb.min_soc) / 100 * bb.capacity_kwh
        return p.cost - left * end, p.cost_without

    now, none = net(hours, plain)
    tot = {"now": now, "none": none, "bigger": net(hours, bigger)[0],
           "sun": net([replace(h, sun=h.sun * MORE_SUN) for h in hours], plain)[0]}
    per_month = 30 / len(days)
    return {"days": len(days), "more_kwh": MORE_KWH, "more_sun_pct": round((MORE_SUN - 1) * 100),
            **{k: round(v * per_month) for k, v in tot.items()}}

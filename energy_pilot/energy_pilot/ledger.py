"""What the power in the battery cost, and what the battery really saved - measured, not estimated.

Every half minute, from the live flow (battery, sun, house, grid):

What the battery holds and what it cost - the same way a weighted average works:
- charging from the grid: the kWh stored get the price paid (the loss in the battery is in it, as only what is
  stored counts)
- charging from the sun: free by default; or, if chosen, worth what the power could have been sold for
- discharging: kWh and cost go down in the same proportion, so the average price stands still
- an empty battery (down at its minimum) starts over at nothing
If another system already keeps this (your AppDaemon's average battery cost), its number is shown instead, so the
two never disagree.

What the battery saved: each moment, what the grid cost with the battery, against what it would have cost
without it (the same house and sun, the battery taken out). Kept per day, so today, this month, this year and in
all are measured on what was really bought and sold.
"""

from __future__ import annotations

from datetime import datetime
import json
import math
from pathlib import Path
from typing import Any

MAX_GAP_H = 0.1  # a longer gap (restart) isn't counted as one long step


class Ledger:
    def __init__(self, data_dir: Path) -> None:
        self.file = data_dir / "energy_pilot_ledger.json"
        self.state: dict[str, Any] = {"stored_kwh": 0.0, "stored_cost": 0.0, "days": {}, "since": None}
        try:
            self.state.update(json.loads(self.file.read_text()))
        except (OSError, ValueError):
            pass
        self._at: datetime | None = None
        self._saved_at = 0.0

    def save(self) -> None:
        try:
            self.file.write_text(json.dumps(self.state, indent=1))
        except OSError:
            pass

    def tick(self, now: datetime, flow: dict[str, Any], price: float | None, sell: float, capacity_kwh: float,
             min_soc: float, efficiency: float, solar_value: str = "free") -> None:
        prev, self._at = self._at, now
        if prev is None or price is None:
            return
        hours = (now - prev).total_seconds() / 3600
        if not 0 < hours <= MAX_GAP_H:
            return
        batt, pv = flow.get("battery"), flow.get("pv") or 0.0
        house, ev, soc, grid = flow.get("house") or 0.0, flow.get("ev") or 0.0, flow.get("soc"), flow.get("grid")
        s = self.state
        s["since"] = s.get("since") or now.date().isoformat()
        if batt is not None:
            if batt > 20:  # charging: what the sun has left over first, the rest from the grid
                kwh = batt / 1000 * hours
                sun_kwh = min(kwh, max(0.0, pv - house - ev) / 1000 * hours)
                grid_kwh = kwh - sun_kwh
                s["stored_kwh"] += kwh * math.sqrt(efficiency)  # only what ends up in the battery
                s["stored_cost"] += grid_kwh * price + (sun_kwh * sell if solar_value == "sell" else 0.0)
            elif batt < -20 and s["stored_kwh"] > 0:  # discharging: the average stays
                out = -batt / 1000 * hours / math.sqrt(efficiency)
                keep = max(0.0, 1 - out / s["stored_kwh"])
                s["stored_kwh"] *= keep
                s["stored_cost"] *= keep
            if soc is not None and capacity_kwh:
                if soc <= min_soc + 1:
                    s["stored_kwh"] = s["stored_cost"] = 0.0  # empty: a new round
                elif s["stored_kwh"] > soc / 100 * capacity_kwh * 1.05:  # never more than the battery holds
                    keep = soc / 100 * capacity_kwh / s["stored_kwh"]
                    s["stored_kwh"] *= keep
                    s["stored_cost"] *= keep
        # Saved: the grid with the battery against the grid without it.
        if grid is None:
            grid = house + ev + (batt or 0.0) - pv
        without = grid - (batt or 0.0)

        def cost(watts: float) -> float:
            kwh = watts / 1000 * hours
            return kwh * price if kwh > 0 else kwh * sell

        day = s["days"].setdefault(now.date().isoformat(), {"saved": 0.0, "cost": 0.0, "without": 0.0, "bought": 0.0, "sold": 0.0})
        c, w = cost(grid), cost(without)
        day["cost"] += c
        day["without"] += w
        day["saved"] += w - c
        day["bought" if grid > 0 else "sold"] += abs(grid) / 1000 * hours
        if now.timestamp() - self._saved_at > 300:
            self._trim(now)
            self.save()
            self._saved_at = now.timestamp()

    def _trim(self, now: datetime) -> None:
        """Days older than two years are summed into one."""
        cut = now.date().replace(year=now.year - 2).isoformat()
        old = [d for d in self.state["days"] if d < cut]
        if old:
            self.state["older"] = round(self.state.get("older", 0.0) + sum(self.state["days"].pop(d)["saved"] for d in old), 2)

    def summary(self, now: datetime, other_avg: float | None = None) -> dict[str, Any]:
        s, days = self.state, self.state["days"]
        d, m, y = now.date().isoformat(), now.strftime("%Y-%m"), str(now.year)

        def total(prefix: str) -> float:
            return round(sum(v["saved"] for k, v in days.items() if k.startswith(prefix)), 2)

        avg = s["stored_cost"] / s["stored_kwh"] if s["stored_kwh"] > 0.05 else None
        return {
            "stored_kwh": round(s["stored_kwh"], 2), "avg_cost": round(other_avg if other_avg is not None else avg, 3) if (other_avg or avg) is not None else None,
            "avg_source": "other" if other_avg is not None else "own",
            "today": total(d), "month": total(m), "year": total(y), "total": round(total("") + s.get("older", 0.0), 2),
            "since": s.get("since"), "today_detail": {k: round(v, 2) for k, v in (days.get(d) or {}).items()},
        }

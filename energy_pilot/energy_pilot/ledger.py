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
MAX_BATT_W = 50_000  # a home battery never moves more - a reading above it is a wrong unit, not power


class Ledger:
    def __init__(self, data_dir: Path) -> None:
        self.file = data_dir / "energy_pilot_ledger.json"
        self.state: dict[str, Any] = {"stored_kwh": 0.0, "stored_cost": 0.0, "days": {}, "since": None}
        try:
            self.state.update(json.loads(self.file.read_text()))
        except (OSError, ValueError):
            pass
        self._seed_all()
        self._repair()
        self._at: datetime | None = None
        self._saved_at = 0.0

    def _seed_all(self) -> None:
        """Sun and battery came later (0.89): the days before it start with what the battery saved - the sun's own
        part wasn't measured then, so it's a little low for them, but it never shows less than the battery alone."""
        s = self.state
        if s.get("all_seeded") or not s.get("since"):
            return
        # 0.89.0 counted sun and battery only from the moment it started: that day also gets the battery's saving
        # from before (the battery's part after it is then counted twice - a little, and only for that one day)
        first = s["days"].get(s.get("all_since") or "")
        if first and "all" in first:
            first["all"] += first.get("saved", 0.0)
        for day in s["days"].values():
            if "all" not in day:
                day["all"] = day.get("saved", 0.0)
        s["older_all"] = s.get("older", 0.0)
        s["all_since"] = s["since"]
        s["all_seeded"] = True

    def _repair(self) -> None:
        """Once: a day saved far more than any other (a battery read in the wrong unit for a while - W taken as kW -
        made "without the battery" thousands) isn't a saving. Such a day counts as nothing rather than a wrong number."""
        s = self.state
        if s.get("repaired_units"):
            return
        s["repaired_units"] = True
        days = s.get("days", {})
        if len(days) < 5:
            return
        for key, day in days.items():
            others = sorted(abs(d.get("saved", 0.0)) for k, d in days.items() if k != key)
            typical = max(others[len(others) // 2], 1.0)
            if abs(day.get("saved", 0.0)) > 20 * typical:
                day["saved"] = day["all"] = 0.0
                day["repaired"] = True

    def save(self) -> None:
        try:
            self.file.write_text(json.dumps(self.state, indent=1))
        except OSError:
            pass

    def tick(self, now: datetime, flow: dict[str, Any], price: float | None, sell: float, capacity_kwh: float,
             min_soc: float, efficiency: float, solar_value: str = "free", max_charge_kw: float = 3.0,
             max_discharge_kw: float = 3.0) -> None:
        prev, self._at = self._at, now
        if prev is None or price is None:
            return
        hours = (now - prev).total_seconds() / 3600
        if not 0 < hours <= MAX_GAP_H:
            return
        batt, pv = flow.get("battery"), flow.get("pv") or 0.0
        if batt is not None and abs(batt) > max(MAX_BATT_W, 3000 * max(max_charge_kw, max_discharge_kw)):
            return  # an impossible reading (a wrong unit) - not counted
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
                s["stored_sun"] = s.get("stored_sun", 0.0) + sun_kwh * math.sqrt(efficiency)  # how much of it is sun
                s["sun_seen"] = s.get("sun_seen", 0.0) + kwh * math.sqrt(efficiency)  # charged since this was kept
            elif batt < -20 and s["stored_kwh"] > 0:  # discharging: the average stays
                out = -batt / 1000 * hours / math.sqrt(efficiency)
                keep = max(0.0, 1 - out / s["stored_kwh"])
                s["stored_kwh"] *= keep
                s["stored_cost"] *= keep
                s["stored_sun"] = s.get("stored_sun", 0.0) * keep
            if soc is not None and capacity_kwh:
                if soc <= min_soc + 1:
                    # Empty: a new round - but only after a few minutes, so one wrong reading (0 % for a moment
                    # when the inverter reconnects) doesn't throw away what the power in the battery cost.
                    since = s.get("low_since") or now.isoformat()
                    s["low_since"] = since
                    if (now - datetime.fromisoformat(since)).total_seconds() >= 300:
                        s["stored_kwh"] = s["stored_cost"] = s["stored_sun"] = 0.0
                        s["sun_seen"] = 1e9  # a new round: all of it is measured
                else:
                    s.pop("low_since", None)
                over = soc > min_soc + 1 and s["stored_kwh"] > soc / 100 * capacity_kwh * 1.05
                if over:  # never more than the battery holds - when the level has said so for a few minutes
                    since = s.get("over_since") or now.isoformat()
                    s["over_since"] = since
                    if (now - datetime.fromisoformat(since)).total_seconds() >= 300:
                        keep = soc / 100 * capacity_kwh / s["stored_kwh"]
                        s["stored_kwh"] *= keep
                        s["stored_cost"] *= keep
                        s["stored_sun"] = s.get("stored_sun", 0.0) * keep
                else:
                    s.pop("over_since", None)
        # Saved: the grid with the battery against the grid without it.
        if grid is None:
            grid = house + ev + (batt or 0.0) - pv
        without = grid - (batt or 0.0)

        def cost(watts: float) -> float:
            kwh = watts / 1000 * hours
            return kwh * price if kwh > 0 else kwh * sell

        day = s["days"].setdefault(now.date().isoformat(), {"saved": 0.0, "cost": 0.0, "without": 0.0, "bought": 0.0, "sold": 0.0})
        # What the power in the battery cost when the day began - so power bought for later isn't a loss today
        day.setdefault("stored_start", round(s["stored_cost"], 4))
        c, w = cost(grid), cost(without)
        day["cost"] += c
        day["without"] += w
        day["saved"] += w - c
        # Sun and battery together: against buying all the house used (grid without battery and sun) - closer to the bill
        day["all"] = day.get("all", 0.0) + cost(without + pv) - c
        s["all_since"] = s.get("all_since") or now.date().isoformat()
        day["bought" if grid > 0 else "sold"] += abs(grid) / 1000 * hours
        # Honest: what Energy Pilot itself adds. The same battery in the inverter's own way (the house first: charged by
        # the sun's surplus, emptied into the house, never from the grid) - run beside the real one, same house and sun.
        if capacity_kwh and soc is not None:
            fresh = s.get("selfuse_day") != now.date().isoformat() or s.get("selfuse_kwh") is None
            day["selfuse"] = day.get("selfuse", 0.0) + cost(self._selfuse(soc, house + ev - pv, hours, capacity_kwh, min_soc,
                                                                          efficiency, max_charge_kw, max_discharge_kw))
            day["cost_p"] = day.get("cost_p", 0.0) + c  # the real cost over the same steps
            # Both start the day at the same level: what one holds more than the other at the end counts at what the
            # power in the battery cost - so power bought cheaply for tomorrow isn't a loss today (and the other way round).
            extra = soc / 100 * capacity_kwh - s["selfuse_kwh"]
            if fresh:  # the day's first step: the two may already differ by that one step - not counted
                s["selfuse_off"] = extra
            extra -= s.get("selfuse_off", 0.0)
            value = s["stored_cost"] / s["stored_kwh"] if s.get("stored_kwh", 0) > 0.5 else price
            day["pilot"] = day["selfuse"] - day["cost_p"] + extra * value
        if now.timestamp() - self._saved_at > 300:
            self._trim(now)
            self.save()
            self._saved_at = now.timestamp()

    def _selfuse(self, soc: float, need_w: float, hours: float, capacity_kwh: float, min_soc: float, efficiency: float,
                 max_charge_kw: float, max_discharge_kw: float) -> float:
        """One step of the battery left to itself: the grid's watts then. Starts at the real level each day."""
        s, floor = self.state, capacity_kwh * min_soc / 100
        if s.get("selfuse_day") != self._at.date().isoformat() or s.get("selfuse_kwh") is None:
            s["selfuse_day"], s["selfuse_kwh"] = self._at.date().isoformat(), soc / 100 * capacity_kwh
        kwh, half = s["selfuse_kwh"], math.sqrt(max(0.5, efficiency))
        if need_w < 0:  # the sun's surplus: into the battery as far as it takes
            take = min(-need_w / 1000 * hours, max_charge_kw * hours, max(0.0, (capacity_kwh - kwh) / half))
            s["selfuse_kwh"] = kwh + take * half
            return need_w + take * 1000 / hours
        give = min(need_w / 1000 * hours, max_discharge_kw * hours, max(0.0, (kwh - floor) * half))
        s["selfuse_kwh"] = kwh - give / half
        return need_w - give * 1000 / hours

    def _trim(self, now: datetime) -> None:
        """Days older than two years are summed into one."""
        cut = now.date().replace(year=now.year - 2).isoformat()
        old = [d for d in self.state["days"] if d < cut]
        if old:
            gone = [self.state["days"].pop(d) for d in old]
            self.state["older"] = round(self.state.get("older", 0.0) + sum(g["saved"] for g in gone), 2)
            self.state["older_all"] = round(self.state.get("older_all", 0.0) + sum(g.get("all", 0.0) for g in gone), 2)

    def summary(self, now: datetime, other_avg: float | None = None) -> dict[str, Any]:
        s, days = self.state, self.state["days"]
        d, m, y = now.date().isoformat(), now.strftime("%Y-%m"), str(now.year)

        def total(prefix: str, key: str = "saved") -> float:
            return round(sum(v.get(key, 0.0) for k, v in days.items() if k.startswith(prefix)), 2)

        avg = s["stored_cost"] / s["stored_kwh"] if s["stored_kwh"] > 0.05 else None
        return {
            "stored_kwh": round(s["stored_kwh"], 2), "avg_cost": round(other_avg if other_avg is not None else avg, 3) if (other_avg or avg) is not None else None,
            "avg_source": "other" if other_avg is not None else "own",
            "today": total(d), "month": total(m),
            # Today with the power still in the battery counted at what it cost: charging for the evening isn't a loss
            # in the morning, and power bought yesterday that is used today counts at its price.
            "today_stored": round(total(d) + s["stored_cost"] - days[d]["stored_start"], 2) if "stored_start" in (days.get(d) or {}) else None, "year": total(y), "total": round(total("") + s.get("older", 0.0), 2),
            # sun vs grid only once most of what's in it was charged while this was kept
            "sun_share": round(min(1.0, s.get("stored_sun", 0.0) / s["stored_kwh"]), 2)
            if s["stored_kwh"] > 0.2 and s.get("sun_seen", 0.0) >= s["stored_kwh"] * 0.6 else None,
            # sun and battery together (kept from when this came in); today as it was really paid, like the battery's
            "all": {"today": total(d, "all"),
                    "month": total(m, "all"), "year": total(y, "all"),
                    "total": round(total("", "all") + s.get("older_all", 0.0), 2), "since": s.get("all_since")}
            if s.get("all_since") else None,
            # what Energy Pilot added against the battery left to itself (the inverter's own house-first way)
            "pilot": {"today": total(d, "pilot"), "month": total(m, "pilot"), "year": total(y, "pilot"), "total": total("", "pilot")}
            if any("pilot" in v for v in days.values()) else None,
            # this month day by day, for the picture to share (both views)
            "month_days": {"bat": [round(days[k].get("saved", 0.0), 2) for k in sorted(days) if k.startswith(m)],
                           "all": [round(days[k].get("all", 0.0), 2) for k in sorted(days) if k.startswith(m)]},
            "since": s.get("since"), "today_detail": {k: round(v, 2) for k, v in (days.get(d) or {}).items()},
        }

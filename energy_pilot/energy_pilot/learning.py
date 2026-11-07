"""Learning from its own results, every night - no dice, just looking back at yesterday with the real numbers.

Every hour the engine writes down what it expected (house use, sun, price). After midnight it compares yesterday's
expectations with what really happened and adjusts:

- sun: how much the solar forecast is usually off, apart for cloudy and clear hours
- house margin: how much the house's use varies from the forecast - added in the expensive hours, so the battery
  doesn't run dry just before they end
- end value: what a kWh left in the battery at the end of the plan is worth - yesterday is planned again with
  the real numbers for a few values, and the one that would have cost least is moved towards
- a report: what the battery saved yesterday and how good the forecasts were

All of it is kept in Energy Pilot's own folder.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import logging
from pathlib import Path
from statistics import mean
from typing import Any

from .engine import Battery, Hour, plan_battery

_LOGGER = logging.getLogger(__name__)
FACTORS = (0.6, 0.75, 0.9, 1.0, 1.1, 1.25)


class Learning:
    def __init__(self, data_dir: Path) -> None:
        self.file = data_dir / "energy_pilot_learning.json"
        self.log_file = data_dir / "energy_pilot_expected.jsonl"
        self.state: dict[str, Any] = {"solar_bias": {"cloudy": 1.0, "clear": 1.0}, "house_margin": 0.0, "end_factor": 1.0,
                                      "reports": [], "reviewed": None}
        try:
            self.state.update(json.loads(self.file.read_text()))
        except (OSError, ValueError):
            pass

    def save(self) -> None:
        self.file.write_text(json.dumps(self.state, indent=1, default=str))

    # ---------- what the engine uses ----------

    def sun(self, kwh: float, cloud: float | None) -> float:
        bias = self.state["solar_bias"]["cloudy" if (cloud or 0) >= 60 else "clear"]
        return kwh * bias

    @property
    def end_factor(self) -> float:
        return float(self.state.get("end_factor", 1.0))

    @property
    def margin(self) -> float:
        return float(self.state.get("house_margin", 0.0))

    # ---------- writing down what was expected ----------

    def expect(self, rows: list[dict[str, Any]]) -> None:
        """rows: [{t, house, sun, price, cloud}] for the coming hours - the first is kept (this hour's best guess)."""
        if not rows:
            return
        try:
            with self.log_file.open("a") as f:
                f.write(json.dumps(rows[0]) + "\n")
        except OSError:
            pass

    def _expected(self, day: str) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        try:
            for line in self.log_file.read_text().splitlines():
                row = json.loads(line)
                if str(row.get("t", "")).startswith(day):
                    out.setdefault(row["t"][:13], row)  # the first guess for each hour
        except (OSError, ValueError):
            pass
        return out

    # ---------- the nightly review ----------

    def review(self, day: datetime, house: dict[str, float], pv: dict[str, float], battery: Battery,
               prices: dict[str, float], soc_start: float | None) -> dict[str, Any] | None:
        """Yesterday with the real numbers. house/pv/prices: {"YYYY-MM-DDTHH": kWh or price}."""
        key = day.strftime("%Y-%m-%d")
        if self.state.get("reviewed") == key:
            return None
        exp = self._expected(key)
        report: dict[str, Any] = {"day": key}
        # How good were the forecasts?
        h_err = [abs(exp[h]["house"] - house[h]) for h in exp if h in house and exp[h].get("house") is not None]
        if h_err:
            report["house_error"] = round(mean(h_err), 3)
            margin = sorted(h_err)[int(len(h_err) * 0.7)] if len(h_err) > 3 else mean(h_err)
            self.state["house_margin"] = round(0.8 * self.margin + 0.2 * margin, 3)
        for kind in ("cloudy", "clear"):
            pairs = [(exp[h]["sun"], pv[h]) for h in exp if h in pv and (exp[h].get("sun") or 0) > 0.2
                     and ((exp[h].get("cloud") or 0) >= 60) == (kind == "cloudy")]
            if len(pairs) >= 3:
                ratio = sum(a for _, a in pairs) / max(0.01, sum(f for f, _ in pairs))
                ratio = min(2.0, max(0.3, ratio))
                b = self.state["solar_bias"]
                b[kind] = round(0.8 * b[kind] * 1 + 0.2 * b[kind] * ratio, 3)  # moves a fifth of the way
                report[f"sun_{kind}"] = round(ratio, 2)
        # What would each end value have cost, planning yesterday with the real numbers?
        hours = [Hour(datetime.fromisoformat(h + ":00:00").replace(tzinfo=day.tzinfo), prices[h], 0.0, house[h], pv.get(h, 0.0))
                 for h in sorted(house) if h in prices]
        if len(hours) >= 18 and soc_start is not None:
            base = sorted(prices[h] for h in prices)[len(prices) // 2]
            costs = {f: plan_battery(hours, soc_start, battery, end_value=base * f).cost for f in FACTORS}
            best = min(costs, key=costs.get)
            self.state["end_factor"] = round(0.75 * self.end_factor + 0.25 * best, 3)
            p = plan_battery(hours, soc_start, battery, end_value=base * self.end_factor)
            report.update(saving=p.saving, cost=p.cost, cost_without=p.cost_without, best_factor=best)
        self.state["reports"] = (self.state.get("reports") or [])[-29:] + [report]
        self.state["reviewed"] = key
        self.save()
        self._trim(day)
        return report

    def _trim(self, day: datetime) -> None:
        """Keep two weeks of expectations."""
        cut = (day - timedelta(days=14)).strftime("%Y-%m-%d")
        try:
            lines = [ln for ln in self.log_file.read_text().splitlines() if json.loads(ln).get("t", "") >= cut]
            self.log_file.write_text("\n".join(lines) + ("\n" if lines else ""))
        except (OSError, ValueError):
            pass

    def summary(self) -> dict[str, Any]:
        reports = self.state.get("reports") or []
        week = reports[-7:]
        return {
            "yesterday": reports[-1] if reports else None,
            "week_saving": round(sum(r.get("saving", 0) for r in week), 2) if week else None,
            "solar_bias": self.state["solar_bias"], "house_margin": self.margin, "end_factor": self.end_factor,
            "days": len(reports),
        }

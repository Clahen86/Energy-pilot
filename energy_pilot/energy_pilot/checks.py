"""Self-check: settings that make the plan worse, each with a plain explanation and (when it can) a one-tap fix.

A wrong number - an import limit set too low, a battery size off by a few kWh - quietly spoils the plan, and
nothing told the user. These checks look at what Energy Pilot has measured and planned, and say so.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


class GridPeak:
    """The most the house has really bought from the grid (kW, two-minute average) - kept for 30 days."""

    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state
        self._recent: list[float] = []

    def see(self, now: datetime, grid_w: float | None) -> None:
        if grid_w is None:
            return
        self._recent = (self._recent + [max(0.0, grid_w) / 1000])[-4:]  # 4 x 30 s
        if len(self._recent) < 4:
            return
        kw = sum(self._recent) / 4
        p = self.state.get("grid_peak") or {}
        old = p.get("at")
        stale = old is None or (now - datetime.fromisoformat(old)).days >= 30
        if stale or kw > p.get("kw", 0):
            self.state["grid_peak"] = {"kw": round(kw, 2), "at": now.isoformat()}

    def kw(self) -> float | None:
        return (self.state.get("grid_peak") or {}).get("kw")


def run(engine: Any, hours: list, b: Any, plan: Any, end_value: float) -> list[dict[str, Any]]:
    """The checks for the plan just made. Each: key, level (warn/info), values for the text, fix (settings) or goto."""
    from .engine import plan_battery

    out: list[dict[str, Any]] = []
    st = engine.ov.settings
    f = engine.ov.flow() or {}

    # 1. The import limit stops the battery charging in the cheap hours.
    if b.import_limit_kw is not None and plan is not None and hours:
        from dataclasses import replace

        free = plan_battery(hours, f["soc"], replace(b, import_limit_kw=None), end_value=end_value)
        lost = round(plan.cost - free.cost, 2)
        if lost > max(0.5, 0.02 * abs(plan.cost_without or 0)):
            out.append({"key": "fuse_blocks", "level": "warn", "vals": {"limit": b.import_limit_kw, "x": lost},
                        "fix": {"import_limit_kw": None}, "goto": "grid"})
    peak = engine.grid_peak.kw() if getattr(engine, "grid_peak", None) else None
    if b.import_limit_kw is not None and peak and peak > b.import_limit_kw * 1.05 and not any(c["key"] == "fuse_blocks" for c in out):
        out.append({"key": "fuse_low", "level": "warn", "vals": {"limit": b.import_limit_kw, "peak": round(peak, 1)},
                    "fix": {"import_limit_kw": None}, "goto": "grid"})

    # 2. Battery size: the usable kWh it has measured differs from what's set.
    from . import batteries

    learned = engine.batt_learn.capacity()
    if learned and not batteries.extras(st) and st.get("battery_kwh") and abs(float(st["battery_kwh"]) - learned) / learned > 0.05:
        out.append({"key": "capacity", "level": "info", "vals": {"set": float(st["battery_kwh"]), "learned": round(learned, 1)},
                    "fix": {"battery_kwh": None}, "goto": "battery"})

    # 3. Is the car part of the house use? The user's choice says otherwise than what it has seen.
    chosen, seen = st.get("ev_in_house"), engine.ev_detected
    if chosen is not None and seen is not None and bool(chosen) != bool(seen):
        out.append({"key": "ev_house", "level": "info", "vals": {"seen": bool(seen)}, "fix": {"ev_in_house": None}, "goto": "car"})

    # 4. Selling from the battery.
    if st.get("battery_export"):
        if not b.export:
            out.append({"key": "export_blocked", "level": "info", "vals": {}, "goto": "battery"})
        elif not st.get("sell") and not engine.ov.role("sell_price"):
            out.append({"key": "export_no_price", "level": "warn", "vals": {}, "fix": {"sell": True}, "goto": "grid"})
        elif plan is not None and hours and not any(s.action == "export" for s in plan.steps):
            best = max(h.sell for h in hours)
            buys = sorted(h.price for h in hours)
            worth = buys[len(buys) // 2]
            if best < worth:  # otherwise something else holds it back - nothing plain to say
                out.append({"key": "export_no_gain", "level": "info", "vals": {"sell": round(best, 2), "worth": round(worth, 2)}})

    # 5. Another battery in Home Assistant that isn't set up.
    main = engine.ov.role("battery_soc")
    if main and not st.get("offgrid"):
        more = batteries.extras(st)
        taken = [b.get("soc") for b in more] + [b.get("power") for b in more]
        for cand in batteries.find(engine.ha.states, main, taken, list(st.get("battery_dismissed") or []))[:1]:
            new = {"name": cand["name"], "soc": cand["soc"], "power": cand["power"]}
            out.append({"key": "battery_found", "level": "info", "vals": {"name": cand["name"]},
                        "fix": {"batteries": list(st.get("batteries") or []) + [new]},
                        "dismiss": {"battery_dismissed": list(st.get("battery_dismissed") or []) + [cand["soc"]]}, "goto": "battery"})

    # 6. Another charger in Home Assistant that isn't set up.
    from . import chargers

    if engine.ov.role("ev_power") or engine.ov.role("ev_plug"):
        more = chargers.extras(st)
        taken = [x for c in more for x in (c.get("power"), c.get("plug"))]
        for cand in chargers.find(engine.ha.states, engine.ov.role("ev_power"), engine.ov.role("ev_plug"), taken,
                                  list(st.get("charger_dismissed") or []))[:1]:
            new = {k: cand[k] for k in ("name", "power", "plug", "session")}
            out.append({"key": "charger_found", "level": "info", "vals": {"name": cand["name"]},
                        "fix": {"chargers": list(st.get("chargers") or []) + [new]},
                        "dismiss": {"charger_dismissed": list(st.get("charger_dismissed") or []) + [cand["power"]]}, "goto": "car"})

    # 7. Things it can't see.
    if f.get("soc") is None and not st.get("offgrid"):
        out.append({"key": "no_soc", "level": "warn", "vals": {}, "goto": "roles"})
    return out

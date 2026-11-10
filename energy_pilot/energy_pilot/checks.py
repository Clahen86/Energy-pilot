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


# The most common main fuse for a house, by country: (kW, as people know it). Only where one size is common.
USUAL_FUSE = {"DK": (17, "3 × 25 A"), "SE": (17, "3 × 25 A"), "FI": (17, "3 × 25 A"), "DE": (24, "3 × 35 A"),
              "AT": (24, "3 × 35 A"), "NL": (17, "3 × 25 A"), "GB": (23, "100 A"), "IE": (14, "63 A")}


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
    # The limit is still the 10 kW new installs start with: the usual main fuse in the country is a better guess.
    st0 = engine.ov.settings
    country = str(((getattr(engine, "ha", None) and engine.ha.config) or {}).get("country") or "").upper()
    usual = USUAL_FUSE.get(country)
    if (usual and st0.get("import_limit_kw") == 10 and not st0.get("fuse_ok") and (peak or 0) <= usual[0]
            and not any(c["key"] in ("fuse_blocks", "fuse_low") for c in out)):
        out.append({"key": "fuse_default", "level": "info", "vals": {"kw": usual[0], "fuse": usual[1]},
                    "fix": {"import_limit_kw": usual[0]}, "dismiss": {"fuse_ok": True}, "goto": "grid"})

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


class FollowWatch:
    """Does the battery do what it's told? If the plan wants it to cover the house (or charge) and it stays at 0 W for
    10 minutes, something on the inverter holds it back - often a rate or limit left at 0 by another system. It says
    so, with the inverter's settings that stand at 0, so it's found for every inverter, known or not."""

    WAIT = 600  # seconds the battery must stay still before it's told
    WORDS = {"discharge": r"discharg|dischg|output|export", "charge": r"(?<!dis)charg|(?<!dis)chg|input"}
    LIMIT = r"rate|power|limit|current|level|max"

    def __init__(self) -> None:
        self.since: datetime | None = None
        self.kind: str | None = None
        self.found: dict[str, Any] | None = None

    def see(self, now: datetime, mode: str | None, want: dict[str, Any] | None, f: dict[str, Any],
            states: dict[str, Any], entities: list[str]) -> None:
        kind = self._expect(mode, want, f)
        batt, grid = f.get("battery"), f.get("grid") or 0.0
        stuck = kind == "discharge" and batt is not None and batt > -100 and grid > 300 \
            or kind == "charge" and batt is not None and batt < 100
        if not stuck:
            self.since, self.kind, self.found = None, None, None
            return
        if self.kind != kind:
            self.since, self.kind, self.found = now, kind, None
        if (now - self.since).total_seconds() >= self.WAIT and self.found is None:
            self.found = {"kind": kind, "at": now.isoformat(), "suspects": self.suspects(kind, states, entities)}
            import logging

            logging.getLogger("energy_pilot.control").warning("The battery doesn't follow the plan (%s): %s", kind, self.found["suspects"])

    @staticmethod
    def _expect(mode: str | None, want: dict[str, Any] | None, f: dict[str, Any]) -> str | None:
        if mode != "control" or not want or f.get("soc") is None:
            return None
        ctx, soc = want.get("ctx") or {}, f["soc"]
        need = (f.get("house") or 0.0) - (f.get("pv") or 0.0)
        if want.get("intent") == "normal" and need > 400 and soc > (ctx.get("min_soc") or 0) + 3:
            return "discharge"
        if want.get("intent") == "charge" and soc < (ctx.get("target") or 0) - 3:
            return "charge"
        return None

    @classmethod
    def suspects(cls, kind: str, states: dict[str, Any], entities: list[str]) -> list[str]:
        """The inverter's numbers that sound like they limit this way and stand at 0 or at their lowest (Sungrow's
        "no battery discharge" is 10 W, the least it takes): "free_mode_discharge_rate = 0"."""
        import re

        out = []
        for e in entities:
            if not e.startswith("number."):
                continue
            name = e.split(".", 1)[1]
            if not (re.search(cls.WORDS[kind], name) and re.search(cls.LIMIT, name)):
                continue
            st = states.get(e) or {}
            try:
                v = float(st.get("state"))
            except (TypeError, ValueError):
                continue
            attrs = st.get("attributes") or {}
            lo, hi = attrs.get("min"), attrs.get("max")
            lowest = isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and 0 < lo and hi >= 20 * lo and v <= lo
            if v == 0 or lowest:
                out.append(f"{name} = {int(v) if v.is_integer() else v}")
        # Modes and switches that stop it outright: Victron's "Keep batteries charged", GivEnergy's pause, "disable charge".
        block = {"discharge": r"keep batteries charged|pause discharg|pause both", "charge": r"pause charg|pause both"}[kind]
        for e in entities:
            st = str((states.get(e) or {}).get("state") or "")
            name = e.split(".", 1)[1]
            if e.startswith("select.") and re.search(block, st, re.I):
                out.append(f"{name} = {st}")
            elif e.startswith("switch.") and st == "on" and re.search(r"disable_charg" if kind == "charge" else r"disable_discharg", name):
                out.append(f"{name} = on")
        return out[:4]

    def check(self) -> list[dict[str, Any]]:
        if not self.found:
            return []
        names = ", ".join(self.found["suspects"])
        key = f"follow_{self.found['kind']}" + ("_why" if names else "")
        return [{"key": key, "level": "warn", "vals": {"list": names}, "goto": "battery"}]

"""The battery's real round trip, measured on the grid.

Many inverters report the battery's power on the battery side, so what they say goes in and out misses the inverter's
own loss (a Growatt SPH: 111 % "round trip" from its own numbers). The grid meter is honest: when the battery starts
or stops, the grid jumps by what the battery really takes or gives - the house doesn't change in that same moment.
Each clean jump gives the share grid/battery for that way; the medians correct the kWh per percent point the battery
learner has seen (blend.BatteryLearner), and their ratio is the round trip from socket to socket.

Step 1 only measures and shows it: the plan doesn't use it yet.
"""

from __future__ import annotations

from statistics import median
from typing import Any

KEEP = 40  # jumps kept per way
NEED = 8  # jumps per way before a number is shown
MIN_JUMP_W = 700
MAX_GAP_S = 75  # samples further apart than this don't make a jump
STEADY_BATT_W = 100
STEADY_GRID_W = 150
STEADY_OTHER_W = 100  # car and sun must stay put across the jump
HIGH_W = 2000  # a jump this big counts as "high power"


def _steady(a: dict[str, float], b: dict[str, float]) -> bool:
    return abs(a["batt"] - b["batt"]) < STEADY_BATT_W and abs(a["grid"] - b["grid"]) < STEADY_GRID_W


class AcSteps:
    def __init__(self, state: dict[str, Any]) -> None:
        self.s = state.setdefault("ac_steps", {"in": [], "out": []})
        self.win: list[dict[str, float]] = []

    def see(self, t: float, f: dict[str, Any]) -> tuple[str, float] | None:
        """A sample of the flow (every 30 s). Returns (way, share) when a clean jump was just seen."""
        try:
            x = {"t": float(t), "grid": float(f["grid"]), "batt": float(f["battery"]),
                 "ev": float(f.get("ev") or 0.0), "pv": float(f.get("pv") or 0.0)}
        except (KeyError, TypeError, ValueError):
            self.win = []
            return None
        if self.win and x["t"] - self.win[-1]["t"] > MAX_GAP_S:
            self.win = []
        self.win = (self.win + [x])[-4:]
        if len(self.win) < 4:
            return None
        s0, s1, s2, s3 = self.win
        if not (_steady(s0, s1) and _steady(s2, s3)):
            return None
        for k in ("ev", "pv"):
            vals = [s[k] for s in self.win]
            if max(vals) - min(vals) >= STEADY_OTHER_W:
                return None
        db = (s2["batt"] + s3["batt"]) / 2 - (s0["batt"] + s1["batt"]) / 2
        dg = (s2["grid"] + s3["grid"]) / 2 - (s0["grid"] + s1["grid"]) / 2
        if abs(db) < MIN_JUMP_W:
            return None
        bs = [s["batt"] for s in self.win]
        way = "in" if min(bs) >= -50 else "out" if max(bs) <= 50 else None
        if way is None:
            return None  # from charging straight to discharging: the two losses mixed
        share = dg / db
        self.win = [s2, s3]  # the same jump isn't counted twice
        if not 0.6 <= share <= 1.4:
            return None  # something else in the house moved too
        self.s[way] = (self.s.get(way) or [])[-(KEEP - 1):] + [[round(share, 3), round(abs(db))]]
        return way, share

    def shares(self) -> tuple[float, float, int] | None:
        """(grid/battery when charging, when discharging, jumps on the thinner side), once there are enough."""
        a, b = self.s.get("in") or [], self.s.get("out") or []
        if len(a) < NEED or len(b) < NEED:
            return None
        return median(x[0] for x in a), median(x[0] for x in b), min(len(a), len(b))

    def round_trip(self, pp: tuple[float, float, int] | None) -> float | None:
        """Socket to socket: the battery's kWh per point out (corrected) over in (corrected). pp from BatteryLearner."""
        sh = self.shares()
        if not sh or not pp:
            return None
        rt = (pp[1] * sh[1]) / (pp[0] * sh[0])
        return round(rt, 3) if 0.5 <= rt <= 1.0 else None

    def info(self, pp: tuple[float, float, int] | None) -> dict[str, Any]:
        a, b = self.s.get("in") or [], self.s.get("out") or []
        out: dict[str, Any] = {"in": len(a), "out": len(b), "need": NEED, "round_trip": self.round_trip(pp)}
        if sh := self.shares():
            out.update(share_in=round(sh[0], 3), share_out=round(sh[1], 3))
        for way, rows in (("in", a), ("out", b)):  # low and high power apart: the inverter's fixed loss weighs at low
            lo, hi = [r[0] for r in rows if r[1] < HIGH_W], [r[0] for r in rows if r[1] >= HIGH_W]
            if len(lo) >= 5:
                out[f"{way}_low"] = round(median(lo), 3)
            if len(hi) >= 5:
                out[f"{way}_high"] = round(median(hi), 3)
        return out

"""A charger in shadow: what Energy Pilot would have done, beside what really happened - so the two can be compared.

When the car is plugged in, the plan Energy Pilot would follow is made once and kept for that charge (it doesn't
shrink as the car's own app or another system fills the car). Meanwhile the charge that really happens is measured:
when it drew power, how much, and what it cost at the prices of those slots. How much a car usually takes is learned
from the charges seen.
"""

from __future__ import annotations

from datetime import datetime
from statistics import median
from typing import Any


class Ghosts:
    def __init__(self, state: dict[str, Any]) -> None:
        self.s = state.setdefault("ghosts", {})

    def part(self, part: str) -> dict[str, Any]:
        return self.s.setdefault(part, {"plug": False, "plan": None, "own": None, "last": None, "needs": []})

    def see(self, part: str, now: datetime, plugged: bool | None, power_w: float | None, price: float | None, dt_s: float) -> None:
        """Every half minute: plugged in or out, and what the charger draws now."""
        if plugged is None:
            return
        g = self.part(part)
        if plugged and not g["plug"]:  # plugged in: a new charge - a new plan will be made
            g["plan"], g["own"] = None, {"start": now.isoformat(), "kwh": 0.0, "cost": 0.0, "first": None, "last": None}
        if not plugged and g["plug"]:  # unplugged: keep what happened, learn how much it took
            own = g.get("own") or {}
            if own.get("kwh", 0) >= 1:
                g["needs"] = (g.get("needs") or [])[-19:] + [round(own["kwh"], 1)]
                g["last"] = {"plan": g.get("plan"), "own": own}
            g["plan"], g["own"] = None, None
        g["plug"] = bool(plugged)
        own = g.get("own")
        if plugged and own is not None and power_w is not None and power_w > 200:
            kwh = power_w / 1000 * dt_s / 3600
            own["kwh"] = round(own["kwh"] + kwh, 5)
            if price is not None:
                own["cost"] = round(own["cost"] + kwh * price, 6)
            own["first"] = own["first"] or now.isoformat()
            own["last"] = now.isoformat()

    def need(self, part: str, setting: float) -> float:
        """How much this car usually takes per charge: learned once it has seen 3 charges, else the setting."""
        n = self.part(part).get("needs") or []
        return round(median(n), 1) if len(n) >= 3 else setting

    def wants_plan(self, part: str) -> bool:
        g = self.part(part)
        return bool(g["plug"]) and g.get("plan") is None

    def set_plan(self, part: str, hours: list[datetime], need: float, prices: dict[datetime, float], kw: float, slot_h: float) -> None:
        left, cost, kwh = need, 0.0, 0.0
        for t in sorted(hours):
            got = min(kw * slot_h, left)
            left -= got
            kwh += got
            cost += got * (prices.get(t) or 0.0)
        self.part(part)["plan"] = {"hours": [t.isoformat() for t in sorted(hours)], "need": round(need, 1),
                                   "kwh": round(kwh, 1), "cost": round(cost, 2), "kw": kw, "slot_h": slot_h}

    def view(self) -> dict[str, Any]:
        """Per charger in shadow: Energy Pilot's charge and the real one, with the average price of each."""
        out = {}
        for part, g in self.s.items():
            plan, own = g.get("plan"), g.get("own")
            if not (plan or own or g.get("last")):
                continue

            def avg(x: dict[str, Any] | None) -> float | None:
                return round(x["cost"] / x["kwh"], 3) if x and x.get("kwh") else None

            out[part] = {"plug": g["plug"], "plan": plan and {**plan, "avg": avg(plan)}, "own": own and {**own, "avg": avg(own)},
                         "last": g.get("last") and {"plan": g["last"]["plan"] and {**g["last"]["plan"], "avg": avg(g["last"]["plan"])},
                                                    "own": {**g["last"]["own"], "avg": avg(g["last"]["own"])}},
                         "learned_kwh": self.need(part, 0) or None}
        return out

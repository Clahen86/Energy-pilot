"""Energy Pilot's own engine - for homes that don't have a system of their own (and to compare with one that does).

1. House forecast: what the house uses, hour by hour, learned from its own history (recent weeks weigh most,
   weekdays and weekends apart).
2. Battery plan: dynamic programming over the hours prices are known - for each hour and battery level, the
   cheapest way on to the end, so the battery is filled when power is cheap or the sun gives too much, and used
   when power is dear. The energy left at the end is valued at what it will likely be worth later.
3. Car plan: the energy the car needs by the time it must be ready - sun first, then the cheapest hours.

Pure functions here (testable without Home Assistant); Engine at the bottom collects the numbers and runs them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
import math
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

_LOGGER = logging.getLogger(__name__)


# ---------- house forecast ----------

def house_profile(rows: list[tuple[datetime, float]], now: datetime) -> dict[tuple[bool, int], float]:
    """{(weekend, hour): kWh} from hourly means (kW) - the last weeks weigh most."""
    sums: dict[tuple[bool, int], float] = {}
    weights: dict[tuple[bool, int], float] = {}
    for when, kw in rows:
        if kw is None or kw < 0 or kw > 50:
            continue
        age_days = max(0.0, (now - when).total_seconds() / 86400)
        w = 0.5 ** (age_days / 10)  # half the weight every 10 days
        key = (when.weekday() >= 5, when.hour)
        sums[key] = sums.get(key, 0.0) + kw * w
        weights[key] = weights.get(key, 0.0) + w
    return {k: sums[k] / weights[k] for k in sums if weights[k] > 0}


def house_forecast(profile: dict[tuple[bool, int], float], hours: list[datetime], fallback: float = 0.6) -> list[float]:
    out = []
    for h in hours:
        v = profile.get((h.weekday() >= 5, h.hour))
        if v is None:
            v = profile.get((not (h.weekday() >= 5), h.hour), fallback)
        out.append(round(v, 3))
    return out


# ---------- battery plan ----------

@dataclass
class Battery:
    capacity_kwh: float = 10.0
    max_charge_kw: float = 3.0
    max_discharge_kw: float = 3.0
    min_soc: float = 10.0  # %
    max_soc: float = 100.0
    efficiency: float = 0.92  # round trip
    grid_charge: bool = True  # may charge from the grid when it pays
    import_limit_kw: float | None = None  # main fuse: never buy more than this in an hour
    quiet: frozenset = frozenset()  # hours (0-23) the battery must not charge


@dataclass
class Hour:
    start: datetime
    price: float  # buy, per kWh
    sell: float  # sell, per kWh (0 when export isn't paid)
    house: float  # kWh
    sun: float  # kWh


@dataclass
class Step:
    start: datetime
    action: str  # "charge_grid", "charge_sun", "discharge", "hold"
    soc_start: float
    soc_end: float
    grid_kwh: float  # + bought, - sold
    cost: float


@dataclass
class Plan:
    steps: list[Step] = field(default_factory=list)
    cost: float = 0.0
    cost_without: float = 0.0  # the same hours without a battery

    @property
    def saving(self) -> float:
        return round(self.cost_without - self.cost, 2)


def plan_battery(hours: list[Hour], soc_now: float, b: Battery, end_value: float | None = None, step_pct: float = 2.0) -> Plan:
    """The cheapest way through the hours, starting at soc_now (%)."""
    if not hours:
        return Plan()
    eff = math.sqrt(b.efficiency)
    levels = [round(b.min_soc + i * step_pct, 4) for i in range(int((b.max_soc - b.min_soc) / step_pct) + 1)]
    if levels[-1] < b.max_soc:
        levels.append(b.max_soc)
    kwh = lambda pct: pct / 100 * b.capacity_kwh  # noqa: E731
    if end_value is None:
        end_value = median(h.price for h in hours) * eff  # what a kWh left over will be worth later
    n, m = len(hours), len(levels)
    INF = float("inf")
    best = [[INF] * m for _ in range(n + 1)]
    choice: list[list[tuple[int, str, float, float]]] = [[(0, "hold", 0.0, 0.0)] * m for _ in range(n)]
    for j, lv in enumerate(levels):
        best[n][j] = -(kwh(lv) - kwh(b.min_soc)) * end_value
    for i in range(n - 1, -1, -1):
        h = hours[i]
        for j, lv in enumerate(levels):
            for k, nxt in enumerate(levels):
                delta = kwh(nxt) - kwh(lv)  # + stored, - taken out (energy in the battery)
                if delta > 0:
                    if delta / eff > b.max_charge_kw + 1e-9:
                        continue
                    into = delta / eff  # what has to go in
                    from_sun = min(into, max(0.0, h.sun - h.house))
                    grid = h.house - h.sun + into
                    if not b.grid_charge and grid > max(0.0, h.house - h.sun) + 1e-9:
                        continue
                    if h.start.hour in b.quiet:
                        continue
                    action = "charge_sun" if into - from_sun < 1e-6 else "charge_grid"
                elif delta < 0:
                    out = -delta * eff  # what comes out to the house
                    if -delta > b.max_discharge_kw + 1e-9:
                        continue
                    need = max(0.0, h.house - h.sun)
                    if out > need + 1e-9:
                        continue  # no exporting from the battery
                    grid = h.house - h.sun - out
                    action = "discharge"
                else:
                    grid = h.house - h.sun
                    action = "hold"
                if b.import_limit_kw is not None and grid > b.import_limit_kw + 1e-9 and delta > 0:
                    continue  # charging would trip the main fuse
                cost = grid * h.price if grid > 0 else grid * h.sell
                total = cost + best[i + 1][k]
                if total < best[i][j] - 1e-12:
                    best[i][j] = total
                    choice[i][j] = (k, action, grid, cost)
    j = min(range(m), key=lambda x: abs(levels[x] - soc_now))
    plan = Plan()
    for i, h in enumerate(hours):
        k, action, grid, cost = choice[i][j]
        plan.steps.append(Step(h.start, action, levels[j], levels[k], round(grid, 3), round(cost, 3)))
        plan.cost += cost
        base = h.house - h.sun
        plan.cost_without += base * h.price if base > 0 else base * h.sell
        j = k
    plan.cost, plan.cost_without = round(plan.cost, 2), round(plan.cost_without, 2)
    return plan


# ---------- car plan ----------

def plan_car(hours: list[Hour], need_kwh: float, charger_kw: float, ready: datetime | None, now: datetime,
             solar_only: bool = False, skip: set | None = None) -> list[datetime]:
    """The hours to charge in: sun surplus first, then the cheapest - all before 'ready' (or within 24 h).
    solar_only: only hours with a real surplus. skip: hours not to use (quiet hours, the battery's sun hours)."""
    if need_kwh <= 0 or charger_kw <= 0:
        return []
    until = ready or now + timedelta(hours=24)
    usable = [h for h in hours if now - timedelta(hours=1) < h.start < until and h.start not in (skip or set())
              and (not solar_only or h.sun - h.house >= charger_kw * 0.5)]
    # A surplus hour costs what the energy would have been sold for; others their price.
    ranked = sorted(usable, key=lambda h: h.sell if h.sun - h.house >= charger_kw * 0.7 else h.price)
    chosen, got = [], 0.0
    for h in ranked:
        if got >= need_kwh:
            break
        chosen.append(h.start)
        got += charger_kw
    return sorted(chosen)


# ---------- running it ----------

ACTION_KIND = {"discharge": "discharge", "charge_sun": "charge", "charge_grid": "grid", "hold": "hold"}


class Engine:
    def __init__(self, ha: Any, overview: Any) -> None:
        self.ha, self.ov = ha, overview
        self.profile: dict[tuple[bool, int], float] = {}
        self.profile_at: datetime | None = None
        self.result: dict[str, Any] | None = None
        self.agree = {"checks": 0, "same": 0}

    def settings(self) -> Battery:
        """The battery as set - a style changes the defaults: "solar" never buys for the battery, "safe" keeps 30 %."""
        s = self.ov.settings
        style = s.get("style") or "cheapest"
        min_soc = float(s.get("battery_min_soc") or 10)
        if style == "safe":
            min_soc = max(min_soc, 30.0)
        grid = bool(s.get("grid_charge", True)) and style != "solar"
        return Battery(
            capacity_kwh=float(s.get("battery_kwh") or self._guess_capacity() or 10),
            max_charge_kw=float(s.get("battery_charge_kw") or 3), max_discharge_kw=float(s.get("battery_discharge_kw") or 3),
            min_soc=min_soc, grid_charge=grid, import_limit_kw=float(s["import_limit_kw"]) if s.get("import_limit_kw") else None,
            quiet=frozenset(self.quiet_hours()) if s.get("quiet_battery") else frozenset(),
        )

    def quiet_hours(self) -> list[int]:
        s = self.ov.settings
        try:
            a, b = int(str(s.get("quiet_from", "")).split(":")[0]), int(str(s.get("quiet_to", "")).split(":")[0])
        except ValueError:
            return []
        return list(range(a, b)) if a < b else list(range(a, 24)) + list(range(0, b))

    def _guess_capacity(self) -> float | None:
        for e, st in self.ha.states.items():
            if e.startswith("sensor.") and "capacity" in e and "batter" in e:
                try:
                    v = float(st.get("state"))
                except (TypeError, ValueError):
                    continue
                if 2 <= v <= 100 and str((st.get("attributes") or {}).get("unit_of_measurement", "kWh")).lower() == "kwh":
                    return v
        return None

    async def learn(self) -> None:
        """The house profile from 28 days of hourly means of the house's power."""
        e = self.ov.role("house_power")
        if not e:
            return
        tz = ZoneInfo(self.ha.config.get("time_zone") or "UTC")
        now = datetime.now(tz)
        try:
            res = await self.ha.call_service("recorder", "get_statistics", {
                "statistic_ids": [e], "period": "hour", "types": ["mean"],
                "start_time": (now - timedelta(days=28)).isoformat(), "end_time": now.isoformat()}, response=True)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("No statistics for %s", e, exc_info=True)
            return
        rows = []
        unit = str(((self.ha.states.get(e) or {}).get("attributes") or {}).get("unit_of_measurement") or "W").lower()
        for r in ((res or {}).get("response") or {}).get("statistics", {}).get(e, []):
            start = r.get("start")
            when = datetime.fromtimestamp(start / 1000, tz) if isinstance(start, (int, float)) else datetime.fromisoformat(str(start)).astimezone(tz)
            mean = r.get("mean")
            if mean is not None:
                rows.append((when, float(mean) / (1 if unit == "kw" else 1000)))
        if rows:
            self.profile = house_profile(rows, now)
            self.profile_at = now

    def run(self) -> dict[str, Any] | None:
        """Plan from now over the hours with prices."""
        plan = self.ov.plan()
        tz = ZoneInfo(self.ha.config.get("time_zone") or "UTC")
        now = datetime.now(tz)
        start = now.replace(minute=0, second=0, microsecond=0)
        rows = [h for h in plan["hours"] if "price" in h and datetime.fromisoformat(h["t"]) >= start]
        if not rows:
            return None
        times = [datetime.fromisoformat(h["t"]) for h in rows]
        house = house_forecast(self.profile, times) if self.profile else [h.get("house", 0.6) for h in rows]
        st = self.ov.settings
        sell = float(st.get("sell_price") or 0) if st.get("sell") else 0.0  # what exported power earns
        hours = [Hour(t, r["price"], sell, house[i], r.get("sun", 0.0)) for i, (t, r) in enumerate(zip(times, rows))]
        # This hour is partly gone: scale it.
        part = 1 - now.minute / 60
        hours[0].house *= part
        hours[0].sun *= part
        f = self.ov.flow()
        result: dict[str, Any] = {"at": now.isoformat(), "house": [{"t": t.isoformat(), "kwh": k} for t, k in zip(times, house)],
                                  "style": st.get("style") or "cheapest"}
        car_plan = self._car(hours, now, f, skip=set()) if (st.get("style") == "car_first") else None
        if car_plan:
            charger = float(st.get("charger_kw") or 7.4)
            for h in hours:
                if h.start in car_plan["set"]:
                    h.house += charger  # the car gets the sun first: what's left goes to the battery
        if f["soc"] is not None:
            b = self.settings()
            p = plan_battery(hours, f["soc"], b)
            result["battery"] = {
                "steps": [{"t": s.start.isoformat(), "action": s.action, "soc": s.soc_end, "grid": s.grid_kwh} for s in p.steps],
                "now": ACTION_KIND[p.steps[0].action] if p.steps else "hold", "target": p.steps[0].soc_end if p.steps else None,
                "cost": p.cost, "cost_without": p.cost_without, "saving": p.saving, "capacity": b.capacity_kwh,
            }
        if car_plan is None:
            skip = set()
            if st.get("style") == "battery_first" and result.get("battery"):
                skip = {datetime.fromisoformat(x["t"]) for x in result["battery"]["steps"] if x["action"] == "charge_sun"}
            car_plan = self._car(hours, now, f, skip)
        if car_plan:
            result["car"] = {"hours": car_plan["hours"], "need_kwh": car_plan["need"]}
        self.result = result
        self._compare()
        return result

    def _car(self, hours: list[Hour], now: datetime, f: dict[str, Any], skip: set) -> dict[str, Any] | None:
        ev, st = self.ov.ev(), self.ov.settings
        if ev is None or not f.get("plug"):
            return None
        need = float(ev.get("cap") or st.get("ev_need_kwh") or 20) - float(ev.get("session_kwh") or 0)
        ready = None
        if ev.get("ready") and ev["ready"] != "00:00:00":
            hh, mm = (int(x) for x in str(ev["ready"]).split(":")[:2])
            ready = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if ready <= now:
                ready += timedelta(days=1)
        if st.get("quiet_car"):
            skip = skip | {h.start for h in hours if h.start.hour in self.quiet_hours()}
        chosen = plan_car(hours, max(0.0, need), float(st.get("charger_kw") or 7.4), ready, now,
                          solar_only=st.get("ev_mode") == "solar", skip=skip)
        return {"hours": [t.isoformat() for t in chosen], "set": set(chosen), "need": round(max(0.0, need), 1)}

    def _compare(self) -> None:
        """How often the engine agrees with the system that controls today (when there is one)."""
        mine = ((self.result or {}).get("battery") or {}).get("now")
        theirs = self.ov.decision("en")
        if mine and theirs and self.ov.role("battery_plan"):
            self.agree["checks"] += 1
            self.agree["same"] += int(mine == theirs["kind"])

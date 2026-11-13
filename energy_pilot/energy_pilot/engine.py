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
import re
from statistics import median
import time
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

_LOGGER = logging.getLogger(__name__)


# ---------- house forecast ----------


def over_cap(hours: list[Hour], p: Plan, cap: float) -> list[Hour]:
    """The paid slots past the day's feed-in cap: per day the best-paid exports are kept up to the cap."""
    by_day: dict[Any, list[tuple[Hour, float]]] = {}
    for h, st in zip(hours, p.steps):
        if h.sell > 0 and st.grid_kwh < 0:
            by_day.setdefault(h.start.date(), []).append((h, -st.grid_kwh))
    out = []
    for rows in by_day.values():
        sold = 0.0
        for h, kwh in sorted(rows, key=lambda r: (-r[0].sell, r[0].start)):
            if sold >= cap - 1e-9:
                out.append(h)
            sold += kwh
    return out


def computed_house(grid: dict, pv: dict, batt: dict, ev: dict, grid_sign: int = 1, batt_sign: int = 1) -> list[tuple[datetime, float]]:
    """kW per hour: grid (buying +) + sun - battery (charging +) - car; never below 0.
    An hour the battery has no history for is left out: counted as 0 its charging would look like house use
    (a battery sensor made lately, or one that was unavailable for a while)."""
    out = []
    for t in sorted(set(grid) & set(pv)):
        if batt and t not in batt:
            continue
        kw = pv[t] + grid[t] * grid_sign - batt.get(t, 0.0) * batt_sign - ev.get(t, 0.0)
        out.append((t, round(max(0.0, kw), 3)))
    return out


def solar_hours(fc: Any, ids: list[str]) -> dict[datetime, float]:
    """Home Assistant's energy/solar_forecast answer -> kWh per hour, the arrays (config entries) added up."""
    out: dict[datetime, float] = {}
    for i in ids:
        for t, wh in (((fc or {}).get(i) or {}).get("wh_hours") or {}).items():
            try:
                dt = datetime.fromisoformat(str(t)).replace(minute=0, second=0, microsecond=0)
                out[dt] = round(out.get(dt, 0.0) + float(wh) / 1000, 3)
            except (TypeError, ValueError):
                continue
    return out

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
    grid_max_soc: float = 100.0  # charging from the grid stops here (the last % wear most); the sun may fill it up
    efficiency: float = 0.92  # round trip
    grid_charge: bool = True  # may charge from the grid when it pays
    import_limit_kw: float | None = None  # main fuse: never buy more than this in an hour
    quiet: frozenset = frozenset()  # hours (0-23) the battery must not charge from the grid (the sun still fills it)
    export: bool = False  # may sell from the battery when it pays (off unless the user turns it on)
    wear: float = 0.0  # what one kWh into or out of the battery wears it (money per kWh) - a move must beat it
    export_limit_kw: float | None = None  # what may be sent to the grid
    taper: tuple = ()  # (from level, share of the charge power it really takes) - learned; most slow down near full
    no_discharge: frozenset = frozenset()  # slots the battery must not discharge in (the car charges on cheap power)
    no_export: frozenset = frozenset()  # slots the battery must not sell in (the user keeps the cheap hours for charging)
    peak_kw: float | None = None  # power tariff: the month's peak so far - buying more costs peak_price per kW
    peak_price: float = 0.0
    targets: tuple = ()  # (hour, minute, soc %): the user wants at least this much in the battery at that time, every day


@dataclass
class Hour:
    start: datetime
    price: float  # buy, per kWh
    sell: float  # sell, per kWh (0 when export isn't paid)
    house: float  # kWh
    sun: float  # kWh
    length: float = 1.0  # hours: 0.25 with quarter-hour prices (Europe since Oct 2025), 0.5 half-hour (UK Agile)


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


def end_price(hours: list[Hour], b: Battery) -> float:
    """What a kWh still in the battery when the plan ends is worth (per kWh stored).

    It's what filling it again costs: the cheap hours, not the average of an expensive day - else the plan keeps
    power it could use in the morning, and even buys at 21:00 to have some left. Only when the plan sees at least
    18 hours (a night with its cheap hours) and the battery may charge from the grid; otherwise the median as before."""
    prices = sorted(h.price for h in hours)
    if not prices:
        return 0.0
    eff = math.sqrt(b.efficiency)
    span = (hours[-1].start - hours[0].start).total_seconds() / 3600 if len(hours) > 1 else 0
    if span < 18 or not b.grid_charge:
        return median(prices) * eff
    return prices[int(len(prices) * 0.1)] / eff


TARGET_PENALTY = 1000.0  # per % short of a target, times the dearest price: a target wins over any saving


def target_levels(hours: list[Hour], targets: tuple) -> dict[int, float]:
    """Slot boundary (index i = before slot i, n = after the last) -> the least % the user wants there."""
    if not hours or not targets:
        return {}
    start, end = hours[0].start, hours[-1].start + timedelta(hours=hours[-1].length)
    bounds = [h.start for h in hours] + [end]
    req: dict[int, float] = {}
    for hh, mm, soc in targets:
        base = start.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        for k in range(-1, 4):
            t = base + timedelta(days=k)
            if start < t <= end:
                i = next(x for x in range(1, len(bounds)) if bounds[x] >= t)
                req[i] = max(req.get(i, 0.0), float(soc))
    return req


def cheap_slots(hours: list[Hour], share: float = 0.25) -> frozenset:
    """The cheap slots: a buy price in the lowest quarter of the span between the cheapest and the dearest.
    On a night tariff (Intelligent Go, Economy 7) that is the night; with flat prices nothing is cheap."""
    prices = [h.price for h in hours]
    if not prices or max(prices) - min(prices) < 1e-6:
        return frozenset()
    cut = min(prices) + share * (max(prices) - min(prices))
    return frozenset(h.start for h in hours if h.price <= cut + 1e-9)


def plan_battery(hours: list[Hour], soc_now: float, b: Battery, end_value: float | None = None, step_pct: float | None = None) -> Plan:
    """The cheapest way through the hours, starting at soc_now (%)."""
    if not hours:
        return Plan()
    if step_pct is None:
        # Small enough that one step is less than the house uses in a slot - else a quarter hour where the house
        # takes 0.2 kWh can't use the battery at all (one 2 % step of 13 kWh is 0.26 kWh).
        step_pct = 2.0 if min(h.length for h in hours) >= 1 else 1.0
    eff = math.sqrt(b.efficiency)
    levels = [round(b.min_soc + i * step_pct, 4) for i in range(int((b.max_soc - b.min_soc) / step_pct) + 1)]
    if levels[-1] < b.max_soc:
        levels.append(b.max_soc)
    kwh = lambda pct: pct / 100 * b.capacity_kwh  # noqa: E731
    if end_value is None:
        end_value = median(h.price for h in hours) * eff  # what a kWh left over will be worth later
    n, m = len(hours), len(levels)
    INF = float("inf")
    pct_step = step_pct / 100 * b.capacity_kwh  # kWh between two levels
    best = [[INF] * m for _ in range(n + 1)]
    choice: list[list[tuple[int, str, float, float]]] = [[(0, "hold", 0.0, 0.0)] * m for _ in range(n)]
    req = target_levels(hours, b.targets)
    pen = TARGET_PENALTY * max(1.0, max(h.price for h in hours))
    for j, lv in enumerate(levels):
        best[n][j] = -(kwh(lv) - kwh(b.min_soc)) * end_value + max(0.0, req.get(n, 0.0) - lv) * pen
    for i in range(n - 1, -1, -1):
        h = hours[i]
        # Only the levels the battery can reach in this slot (a quarter of an hour moves it a quarter as far).
        up = int(b.max_charge_kw * h.length * eff / pct_step) + 2
        down = int(b.max_discharge_kw * h.length / pct_step) + 2
        for j, lv in enumerate(levels):
            for k in range(max(0, j - down), min(m, j + up + 1)):
                nxt = levels[k]
                delta = kwh(nxt) - kwh(lv)  # + stored, - taken out (energy in the battery)
                if delta > 0:
                    share = next((sh for lvl, sh in sorted(b.taper, reverse=True) if lv >= lvl), 1.0)
                    if delta / eff > b.max_charge_kw * share * h.length + 1e-9:
                        continue  # more than it takes at this level (it slows down when nearly full)
                    into = delta / eff  # what has to go in
                    from_sun = min(into, max(0.0, h.sun - h.house))
                    grid = h.house - h.sun + into
                    if not b.grid_charge and grid > max(0.0, h.house - h.sun) + 1e-9:
                        continue
                    action = "charge_sun" if into - from_sun < 1e-6 else "charge_grid"
                    if h.start.hour in b.quiet and action == "charge_grid":
                        continue  # quiet hours: nothing bought for the battery - the sun's surplus still goes in
                    if action == "charge_grid" and nxt > b.grid_max_soc + 1e-9:
                        continue  # not above the grid limit with power bought - only the sun fills it beyond
                elif delta < 0:
                    if h.start in b.no_discharge:
                        continue  # the car charges on cheap power now: it takes it from the grid, not the battery
                    out = -delta * eff  # what comes out to the house
                    if -delta > b.max_discharge_kw * h.length + 1e-9:
                        continue
                    need = max(0.0, h.house - h.sun)
                    action = "discharge"
                    if out > need + 1e-9:
                        if b.export and h.sell > 0 and h.start not in b.no_export:
                            action = "export"  # sells what the house doesn't use
                        elif k != j - 1 or need <= 0:
                            continue  # no exporting from the battery
                        else:
                            out = need  # the smallest step is more than the house needs: it covers the house, no more
                    grid = h.house - h.sun - out
                    if action == "export" and b.export_limit_kw is not None and -grid > b.export_limit_kw * h.length + 1e-9:
                        continue  # more than may go out on the grid
                else:
                    grid = h.house - h.sun
                    action = "hold"
                if b.import_limit_kw is not None and grid > b.import_limit_kw * h.length + 1e-9 and delta > 0:
                    continue  # charging would trip the main fuse
                cost = grid * h.price if grid > 0 else grid * h.sell
                cost += abs(delta) * b.wear  # every kWh in or out wears the battery: a move must pay for that too
                if b.peak_kw is not None and b.peak_price and grid / h.length > b.peak_kw:
                    cost += (grid / h.length - b.peak_kw) * b.peak_price  # a new peak raises the month's power tariff
                # Equal prices (a night tariff): charge in the first slots, not the last - a battery that slows down
                # near full, or a slot the supplier moves, then still leaves it full. Far too small to change a choice
                # where prices differ (at most 0.0002 per kWh over two days of quarter hours).
                early = delta * i * 1e-6 if delta > 0 else 0.0
                total = cost + early + best[i + 1][k]
                if total < best[i][j] - 1e-12:
                    best[i][j] = total
                    choice[i][j] = (k, action, grid, cost)
        if i in req and i > 0:
            for j, lv in enumerate(levels):
                if lv < req[i]:
                    best[i][j] += (req[i] - lv) * pen  # short of what the user wants at this time
    j = min(range(m), key=lambda x: abs(levels[x] - soc_now))
    plan = Plan()
    for i, h in enumerate(hours):
        k, action, grid, cost = choice[i][j]
        plan.steps.append(Step(h.start, action, levels[j], levels[k], round(grid, 3), round(cost, 3)))
        plan.cost += cost
        base = h.house - h.sun
        plan.cost_without += base * h.price if base > 0 else base * h.sell
        if b.peak_kw is not None and b.peak_price and base / h.length > b.peak_kw:
            plan.cost_without += (base / h.length - b.peak_kw) * b.peak_price
        j = k
    plan.cost, plan.cost_without = round(plan.cost, 2), round(plan.cost_without, 2)
    return plan


def battery_targets(s: dict[str, Any]) -> tuple:
    """The user's "at least X % at HH:MM" from the settings, as (hour, minute, soc); bad rows are left out."""
    out = []
    for t in s.get("battery_targets") or []:
        try:
            hh, mm = (int(x) for x in str(t.get("time")).split(":")[:2])
            soc = float(t.get("soc"))
        except (TypeError, ValueError, AttributeError):
            continue
        if 0 <= hh < 24 and 0 <= mm < 60 and 0 < soc <= 100:
            out.append((hh, mm, soc))
    return tuple(out)


# ---------- car plan ----------

def plan_car(hours: list[Hour], need_kwh: float, charger_kw: float, ready: datetime | None, now: datetime,
             solar_only: bool = False, skip: set | None = None) -> list[datetime]:
    """The hours to charge in: sun surplus first, then the cheapest - all before 'ready' (or within 24 h).
    solar_only: only hours with a real surplus. skip: hours not to use (quiet hours, the battery's sun hours)."""
    if need_kwh <= 0 or charger_kw <= 0:
        return []
    until = ready or now + timedelta(hours=24)
    usable = [h for h in hours if now - timedelta(hours=h.length) < h.start < until and h.start not in (skip or set())
              and (not solar_only or h.sun - h.house >= charger_kw * h.length * 0.5)]
    # A surplus slot costs what the energy would have been sold for; others their price.
    ranked = sorted(usable, key=lambda h: h.sell if h.sun - h.house >= charger_kw * h.length * 0.7 else h.price)
    chosen, got = [], 0.0
    for h in ranked:
        if got >= need_kwh:
            break
        chosen.append(h.start)
        got += charger_kw * h.length
    return sorted(chosen)


# ---------- quarter-hour slots ----------

def resolution(prices: dict[datetime, float], now: datetime) -> int:
    """Minutes between prices from now on: 15 (Europe since October 2025), 30 (UK Agile) or 60."""
    coming = sorted(t for t in prices if t >= now - timedelta(hours=1))[:12]
    gaps = [round((b - a).total_seconds() / 60) for a, b in zip(coming, coming[1:])]
    gap = min((g for g in gaps if g > 0), default=60)
    return 15 if gap <= 15 else 30 if gap <= 30 else 60


def split_slots(hours: list[Hour], prices: dict[datetime, float], now: datetime,
                sells: dict[datetime, float] | None = None) -> list[Hour]:
    """Hours split into the market's price slots, each with its own price."""
    res = resolution(prices, now) if prices else 60
    k = 60 // res
    out = []
    for h in hours:
        for i in range(k):
            start = h.start + timedelta(minutes=i * res)
            if start + timedelta(minutes=res) <= now:
                continue  # already gone
            price = prices.get(start, h.price) if k > 1 else h.price
            sell = sells.get(start, h.sell) if sells and k > 1 else h.sell
            out.append(Hour(start, price, sell, h.house / k, h.sun / k, res / 60))
    # The slot now is planned whole, not scaled to what's left of it: late in a quarter the house would use less than one
    # battery step, and the plan would hold the battery for the rest of it while the house bought from the grid.
    return out


# ---------- running it ----------

ACTION_KIND = {"discharge": "discharge", "charge_sun": "charge", "charge_grid": "grid", "hold": "hold", "export": "export"}


class Engine:
    def __init__(self, ha: Any, overview: Any) -> None:
        from .sources import HouseModel

        from .learning import Learning

        self.ha, self.ov = ha, overview
        self.learning = Learning(overview.file.parent)
        from .ledger import Ledger

        self.ledger = Ledger(overview.file.parent)
        from .blend import BatteryLearner, Habits, Mixer, PriceModel, SolarModel

        self.mixer = Mixer(self.learning.state)
        self.solar_model = SolarModel()
        self.price_model = PriceModel(overview.file.parent)
        self.price_days = 0
        self.habits = Habits(self.learning.state)
        from .ghost import Ghosts

        self.ghosts = Ghosts(self.learning.state)
        from .househist import HouseHistory

        self.house_hist = HouseHistory(self.learning.state)
        from .things import Things

        self.things = Things(self.learning.state)
        self.batt_learn = BatteryLearner(self.learning.state)
        from .checks import GridPeak

        self.grid_peak = GridPeak(self.learning.state)  # the most the house has really bought
        from .powertariff import MonthPeak

        self.month_peak = MonthPeak(self.learning.state)  # the month's peaks, for a power tariff
        self.checks: list[dict[str, Any]] = []
        from .checks import FollowWatch

        self.follow = FollowWatch()  # does the battery do what the plan says (see checks.py)
        from .evsoc import CarSize

        self.car_size = CarSize(self.learning.state)  # the car's battery, learned from the charger (see evsoc.py)
        self.weather: Any = None
        self.house_model = HouseModel()
        self.house_stats_hours: int | None = None  # hours of house history Home Assistant's statistics gave (None: not looked yet)
        self.own_at_learn = False  # the own-history setting when the house model last learned
        self.house_source = "stats"  # where the house model learned from: "stats" or "own" (Energy Pilot's own history)
        self.solar_factors: dict[int, float] = {}
        self.own_prices: list[dict[str, Any]] = []
        self.service_prices: list[dict[str, Any]] = []  # from an integration's action (Nord Pool, Tibber …)
        self.agile_forecast: dict[datetime, float] = {}  # Agile Predict (UK Octopus Agile)
        self.own_solar: dict[datetime, float] = {}
        self.ha_solar: dict[datetime, float] = {}  # Home Assistant's Energy dashboard forecast (kWh per hour)
        self._prices_at = 0.0
        self.profile: dict[tuple[bool, int], float] = {}
        self.profile_at: datetime | None = None
        self.result: dict[str, Any] | None = None
        self.agree = {"checks": 0, "same": 0}
        self.house_so_far: float | None = None  # kWh the house has used today, from the statistics
        self.ev_detected: bool | None = None  # is the car in the house's use? (see evsplit.py)
        self._sign_prev: tuple[float, float] | None = None

    def settings(self) -> Battery:
        """The battery as set - a style changes the defaults: "solar" never buys for the battery, "safe" keeps 30 %."""
        s = self.ov.settings
        style = s.get("style") or "cheapest"
        kind = self.battery_type()["type"]
        from .batterytype import TYPES

        # Lead batteries like to stay above half - unless the user set the minimum.
        min_soc = float(s.get("battery_min_soc") or TYPES[kind]["min_soc"])
        if style == "safe":
            min_soc = max(min_soc, 30.0)
        grid = bool(s.get("grid_charge", True)) and style != "solar"
        ctl = getattr(self.ov, "controller", None)
        if ctl is not None:
            from .adapters import PROFILES

            if (PROFILES.get(ctl.profile_key() or "") or {}).get("grid_charge") is False:
                grid = False  # this battery can't charge from the grid (EcoFlow PowerStream)
        # What the user set wins; then the capacity it has learned (the usable kWh); then a guess.
        cap = float(s.get("battery_kwh") or self.batt_learn.capacity() or self._guess_capacity() or 10)
        # Discharge as charge unless set on its own (extra chargers can make charging faster).
        charge = float(s.get("battery_charge_kw") or 3)
        discharge = float(s.get("battery_discharge_kw") or s.get("battery_charge_kw") or 3)
        from . import batteries

        if more := batteries.extras(s):
            # More than one battery: planned as one, everything added up.
            cap = self.ov.main_battery_kwh() + sum(float(b.get("kwh") or 10) for b in more)
            charge += sum(float(b.get("charge_kw") or 3) for b in more)
            discharge += sum(float(b.get("discharge_kw") or b.get("charge_kw") or 3) for b in more)
        targets = battery_targets(s)
        return Battery(
            capacity_kwh=cap,
            max_charge_kw=charge,
            max_discharge_kw=discharge,
            min_soc=min_soc, grid_charge=grid, import_limit_kw=float(s["import_limit_kw"]) if s.get("import_limit_kw") else None,
            quiet=frozenset(self.quiet_hours("battery")),
            efficiency=self.batt_learn.efficiency(TYPES[kind]["eff"]),  # the type's, until it has seen the real one
            export=self.can_export(),
            wear=self.wear(cap),
            export_limit_kw=float(s["export_limit_kw"]) if s.get("export_limit_kw") else None,
            taper=self.batt_learn.taper(),
            grid_max_soc=max([self.grid_max_soc(kind)] + [t[2] for t in targets]),  # a target may go past the limit
            targets=targets,
            peak_kw=(pt := self.power_tariff()) and pt["limit_kw"],
            peak_price=pt["price_per_kw"] if pt else 0.0,
        )

    def grid_max_soc(self, kind: str) -> float:
        """How full the battery may be charged from the grid: as set, else 95 % (NMC 90 %). Every 14 days without a
        full battery (winter, little sun) it may go to 100 % once, so the battery balances its cells."""
        s = self.ov.settings
        limit = 90.0 if kind == "nmc" else 95.0
        try:
            set_to = float(s.get("battery_grid_max"))
        except (TypeError, ValueError):
            set_to = None
        # 0 or anything at or below the minimum would stop all charging from the grid - a slip, not a wish: ignored.
        if set_to is not None and float(s.get("battery_min_soc") or 0) < set_to <= 100:
            limit = set_to
        if limit < 100 and self.batt_learn.days_since_full() >= 14:
            return 100.0
        return limit

    def power_tariff(self) -> dict[str, Any] | None:
        """A power tariff, when the user set its price: the peak to stay under, and what a kW above it costs."""
        from . import powertariff

        s = self.ov.settings
        try:
            price = float(s.get("power_tariff_price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        if price <= 0:
            return None
        window, count = powertariff.kind(s, self.ha.config.get("country"))
        return {"limit_kw": self.month_peak.limit(count), "price_per_kw": price / count, "window": window, "count": count,
                "level_kw": self.month_peak.level(count)}

    def can_export(self) -> bool:
        """Selling from the battery: when the user turned it on - and the inverter profile can (if one is chosen)."""
        if not self.ov.settings.get("battery_export"):
            return False
        ctl = getattr(self.ov, "controller", None)
        steps = ctl.profile_steps() if ctl is not None else None
        if steps is None:
            return True  # no inverter chosen yet: the plan shows what selling would do
        if not steps.get("export"):
            return False
        try:
            return not ctl.check().get("export", {}).get("missing")  # its controls are there
        except Exception:  # noqa: BLE001
            return True

    def battery_type(self) -> dict[str, Any]:
        """The battery's kind - chosen, or found (the inverter's setting, the model, the learned efficiency)."""
        from . import batterytype

        chosen = self.ov.settings.get("battery_type")
        now = time.time()
        if getattr(self, "_btype", None) is None or now - self._btype[0] > 600:
            ctl = getattr(self.ov, "controller", None)
            info = self.batt_learn.info(0.92)
            found = batterytype.detect(self.ha.states, getattr(ctl, "model", None), self.ov.role("battery_soc"),
                                       info.get("efficiency"), info.get("seen") or 0)
            self._btype = (now, found)
        found = self._btype[1]
        if chosen in batterytype.TYPES:
            return {**found, "type": chosen, "why": "chosen"}
        return found

    def wear(self, capacity_kwh: float | None = None, own: bool = True) -> float:
        """Money per kWh into or out of the battery. Set outright, or worked out from the type (and the price paid)."""
        from . import batterytype

        s = self.ov.settings
        if own and s.get("battery_wear") not in (None, ""):
            return float(s["battery_wear"])
        bt = self.battery_type()
        cap = capacity_kwh or float(s.get("battery_kwh") or self.batt_learn.capacity() or self._guess_capacity() or 10)
        price = float(s["battery_price"]) if s.get("battery_price") not in (None, "") else None
        return batterytype.wear(bt["type"], str(self.ha.config.get("currency") or "EUR"), cap, price, bt.get("cycles"))

    def quiet_hours(self, what: str) -> list[int]:
        """The hours the battery or the car must not charge - each has its own (older settings: one shared period)."""
        s = self.ov.settings
        start, end = s.get(f"quiet_{what}_from"), s.get(f"quiet_{what}_to")
        if not (start and end) and s.get(f"quiet_{what}") is True:
            start, end = s.get("quiet_from"), s.get("quiet_to")
        try:
            a, b = int(str(start).split(":")[0]), int(str(end).split(":")[0])
        except ValueError:
            return []
        if a == b:
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

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.ha.config.get("time_zone") or "UTC")

    async def _hourly_kw(self, entity_id: str, days: int) -> list[tuple[datetime, float]]:
        """Hourly mean power (kW) from the recorder's statistics."""
        tz = self.tz
        now = datetime.now(tz)
        try:
            res = await self.ha.call_service("recorder", "get_statistics", {
                "statistic_ids": [entity_id], "period": "hour", "types": ["mean"],
                "start_time": (now - timedelta(days=days)).isoformat(), "end_time": now.isoformat()}, response=True)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("No statistics for %s", entity_id, exc_info=True)
            return []
        unit = str(((self.ha.states.get(entity_id) or {}).get("attributes") or {}).get("unit_of_measurement") or "W").lower()
        rows = []
        for r in ((res or {}).get("response") or {}).get("statistics", {}).get(entity_id, []):
            start, mean = r.get("start"), r.get("mean")
            if mean is None:
                continue
            when = datetime.fromtimestamp(start / 1000, tz) if isinstance(start, (int, float)) else datetime.fromisoformat(str(start)).astimezone(tz)
            rows.append((when, float(mean) / (1 if unit == "kw" else 1000)))
        return rows

    async def _hourly_sum(self, entities: list[str], days: int) -> dict[datetime, float]:
        """Hourly kW of several sensors added up (two solar arrays)."""
        total: dict[datetime, float] = {}
        for e in entities:
            for w, kw in await self._hourly_kw(e, days):
                total[w] = total.get(w, 0.0) + kw
        return total

    async def _house_rows(self, days: int) -> list[tuple[datetime, float]]:
        """The house's use per hour, without the car: its own sensor, or worked out from the other meters."""
        if e := self.ov.role("house_power"):
            rows = await self._hourly_kw(e, days)
            if rows and self.ev_in_house() and (ev_e := self.ov.role("ev_power")):
                from . import evsplit

                rows = evsplit.subtract(rows, list((await self._all_cars(days)).items()))
            return rows
        if self.ov.role("grid_power") and self.ov.role_all("pv_power"):
            return await self._computed_house(days)
        return []

    async def _all_cars(self, days: int) -> dict[datetime, float]:
        """kW per hour of every charger: charger 1 and the extra ones (settings → chargers)."""
        from . import chargers

        ents = [e for e in [self.ov.role("ev_power")] + [c.get("power") for c in chargers.extras(self.ov.settings)] if e]
        return await self._hourly_sum(ents, days) if ents else {}

    async def _computed_house(self, days: int) -> list[tuple[datetime, float]]:
        """The house's use from the history of the other meters, the way the panel works it out for now: what comes
        from the grid and the sun, less what goes into the battery and the car. Only hours where grid and sun are known."""
        grid = dict(await self._hourly_kw(self.ov.role("grid_power"), days))
        pv = await self._hourly_sum(self.ov.role_all("pv_power"), days)
        batt = dict(await self._hourly_kw(b, days)) if (b := self.ov.role("battery_power")) else {}
        ev = await self._all_cars(days)
        return computed_house(grid, pv, batt, ev, self.ov.grid_sign(), self.ov.battery_sign())

    async def learn(self) -> None:
        """Once a day: weather for the past weeks, the house model, and what the solar panels make of sunlight."""
        from .sources import Weather, learn_solar

        from . import sources

        sources.COUNTRY = (self.ha.config.get("country") or "DK").upper()
        now = datetime.now(self.tz)
        if self.weather is None and self.ha.session is not None and self.ha.config.get("latitude") is not None:
            self.weather = Weather(self.ha.session, float(self.ha.config["latitude"]), float(self.ha.config["longitude"]), self.tz)
        if self.weather is not None:
            try:
                await self.weather.refresh()
            except Exception:  # noqa: BLE001 - no internet: learn without weather
                _LOGGER.info("No weather from Open-Meteo - learning without it")
        rows = []
        if e := self.ov.role("house_power"):
            rows = await self._hourly_kw(e, 60)
        elif self.ov.role("grid_power") and self.ov.role_all("pv_power"):
            rows = await self._computed_house(60)  # no house sensor: grid + sun - battery - car, hour by hour
        self.house_stats_hours = len(rows)
        self.own_at_learn = bool(self.ov.settings.get("own_history"))
        own = self.house_hist.rows() if self.ov.settings.get("own_history") else []
        self.house_source = "own" if len(own) > len(rows) else "stats"
        if self.house_source == "own":
            rows = own  # already without the car
        elif rows:
            if self.ov.role("house_power") and (ev_e := self.ov.role("ev_power")):
                from . import evsplit

                ev_rows = await self._hourly_kw(ev_e, 60)
                self.ev_detected = evsplit.detect(rows, ev_rows)
                if self.ev_in_house():
                    rows = evsplit.subtract(rows, list((await self._all_cars(60)).items()))  # the cars are planned on their own
        if rows:
            self.profile = house_profile(rows, now)
            self.profile_at = now
            try:
                self.house_model.train(rows, self.weather if self.weather and self.weather.hours else None, now)
            except Exception:  # noqa: BLE001 - the profile is used instead
                _LOGGER.warning("House model failed", exc_info=True)
        if self.ov.role_all("pv_power") and self.weather and self.weather.hours:
            pv = await self._hourly_sum(self.ov.role_all("pv_power"), 60)
            self.solar_factors = learn_solar(pv, self.weather)
            try:
                self.solar_model.train(pv, self.weather)
            except Exception:  # noqa: BLE001 - the simple solar forecast is used
                _LOGGER.warning("Solar model failed", exc_info=True)
        try:
            self.price_days = self.price_model.train(self.weather, self.tz)
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Price model failed", exc_info=True)

    def agile_region(self) -> str | None:
        """Octopus Agile (UK): the region letter (A-P) from the tariff code on the price entities - or as set."""
        if r := str(self.ov.settings.get("agile_region") or "").strip().upper():
            return r if re.fullmatch(r"[A-P]", r) else None
        from .pricefeed import companions

        e = self.ov.role("price")
        if not e:
            return None
        for ent in [e, *companions(self.ha.states, e)]:
            for v in ((self.ha.states.get(ent) or {}).get("attributes") or {}).values():
                if isinstance(v, str) and (m := re.search(r"AGILE[A-Z0-9-]*-([A-P])$", v.upper())):
                    return m[1]
        return None

    async def refresh_agile_predict(self) -> None:
        """Agile Predict (agilepredict.com): a forecast of Octopus Agile prices trained on the whole UK market - far
        better than one home's history. Used for Agile until the real prices are out; asked every hour."""
        region = self.agile_region()
        if not region:
            self.agile_forecast = {}
            return
        if time.time() - getattr(self, "_agile_at", 0.0) < 3600 or self.ha.session is None:
            return
        self._agile_at = time.time()
        try:
            async with self.ha.session.get(f"https://agilepredict.com/api/{region}", params={"days": 3},
                                           timeout=aiohttp.ClientTimeout(total=30)) as r:
                data = await r.json(content_type=None)
            rows = (data[0] if isinstance(data, list) and data else {}).get("prices") or []
            out = {}
            for p in rows:
                t = datetime.fromisoformat(str(p["date_time"]).replace("Z", "+00:00")).astimezone(self.tz)
                out[t] = float(p["agile_pred"]) / 100  # pence -> pounds, like the Octopus integration
            if out:
                self.agile_forecast = out
        except Exception as err:  # noqa: BLE001 - the own estimate takes over
            _LOGGER.info("Agile Predict not reachable: %s", err)

    async def refresh_service_prices(self) -> None:
        """Integrations that give the coming prices only through an action (Nord Pool and Tibber built into Home
        Assistant, EnergyZero, easyEnergy): asked every half hour for today and tomorrow."""
        e = self.ov.role("price")
        if not e or time.time() - getattr(self, "_svc_at", 0.0) < 1800 or self.ha.session is None:
            return
        try:
            reg = await self.ha.command({"type": "config/entity_registry/get", "entity_id": e})
        except Exception:  # noqa: BLE001
            return
        platform, entry = reg.get("platform"), reg.get("config_entry_id")
        if platform not in ("nordpool", "tibber", "energyzero", "easyenergy"):
            self.service_prices = []
            return
        self._svc_at = time.time()
        now = datetime.now(self.tz)
        day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
        rows: list[dict[str, Any]] = []

        async def ask(domain: str, service: str, data: dict[str, Any]) -> Any:
            try:
                res = await self.ha.call_service(domain, service, data, response=True)
            except Exception:  # noqa: BLE001 - tomorrow not out yet, or the action failed
                _LOGGER.debug("%s.%s failed", domain, service, exc_info=True)
                return None
            return (res or {}).get("response", res)

        if platform == "nordpool":
            for d in (day0, day0 + timedelta(days=1)):
                r = await ask("nordpool", "get_prices_for_date", {"config_entry": entry, "date": d.date().isoformat()}) or {}
                area = next((v for v in r.values() if isinstance(v, list)), [])
                rows += [{"start": x.get("start"), "price": x.get("price")} for x in area]
            vals = sorted(x["price"] for x in rows if isinstance(x.get("price"), (int, float)))
            if vals and vals[len(vals) // 2] > 20:  # per MWh, as the exchange gives it
                rows = [{**x, "price": x["price"] / 1000} for x in rows if isinstance(x.get("price"), (int, float))]
        elif platform == "tibber":
            r = await ask("tibber", "get_prices", {"start": day0.isoformat(), "end": (day0 + timedelta(days=2)).isoformat()}) or {}
            homes = (r.get("prices") or {}) if isinstance(r, dict) else {}
            home = next(iter(homes.values()), []) if homes else []
            rows = [{"start": x.get("start_time"), "price": x.get("price")} for x in home]
        else:
            service = "get_energy_prices" if platform == "energyzero" else "get_energy_usage_prices"
            r = await ask(platform, service, {"config_entry": entry, "incl_vat": True, "start": day0.isoformat(),
                                               "end": (day0 + timedelta(days=2)).isoformat()}) or {}
            rows = [{"start": x.get("start") or x.get("timestamp"), "price": x.get("price")} for x in (r.get("prices") or [])]
        self.service_prices = [x for x in rows if x.get("start") and isinstance(x.get("price"), (int, float))]

    async def refresh_sources(self) -> None:
        """Every few minutes: weather (hourly), and own prices/solar forecast where the home has none."""
        from .sources import fetch_prices, price_area, solar_forecast

        if self.weather is not None:
            try:
                await self.weather.refresh()
            except Exception:  # noqa: BLE001
                pass
        st = self.ov.settings
        country = (self.ha.config.get("country") or "").upper()
        from .sources import ZONES, tou_prices

        use_tou = st.get("price_source") == "tou" or (st.get("price_source") in (None, "auto") and country not in ZONES and st.get("tou"))
        if not self.ov.role("price") and use_tou and st.get("tou"):
            self.own_prices = tou_prices(st["tou"], self.tz)  # the user's own tariff plan
        elif time.time() - self._prices_at > 1800 and self.ha.session is not None and (country in ZONES or st.get("price_area")):
            # Also with a price integration: its missing hours (tomorrow not out there yet) are filled from these.
            area = st.get("price_area") or price_area(float(self.ha.config.get("latitude") or 56), float(self.ha.config.get("longitude") or 10),
                                                      self.ha.config.get("country"))
            try:
                self.own_prices = await fetch_prices(self.ha.session, area, self.tz, st, self.ha.config.get("currency") or "EUR")
                self._prices_at = time.time()
            except Exception:  # noqa: BLE001
                _LOGGER.info("No prices from Energi Data Service right now")
        # Its own (learned) forecast is always made: it's used when no forecast in the home gives the sun hour by hour.
        if self.solar_factors and self.weather:
            start = datetime.now(self.tz).replace(minute=0, second=0, microsecond=0)
            self.own_solar = solar_forecast(self.solar_factors, self.weather, [start + timedelta(hours=i) for i in range(48)])
        await self.refresh_ha_solar()

    async def refresh_ha_solar(self) -> None:
        """The solar forecasts set up in Home Assistant's Energy dashboard (Forecast.Solar, Open-Meteo, Solcast …),
        hour by hour - the same numbers the Energy dashboard shows. Their sensors alone don't carry the hours."""
        try:
            prefs = await self.ha.command({"type": "energy/get_prefs"})
            ids = [i for src in (prefs or {}).get("energy_sources") or [] if src.get("type") == "solar"
                   for i in src.get("config_entry_solar_forecast") or []]
            if not ids:
                self.ha_solar = {}
                return
            fc = await self.ha.command({"type": "energy/solar_forecast"})
        except Exception:  # noqa: BLE001
            return
        self.ha_solar = solar_hours(fc, ids)

    async def refresh_house_today(self) -> None:
        """What the house has used so far today (whole hours from the statistics, plus this hour's share)."""
        now = datetime.now(self.tz)
        day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
        rows = await self._house_rows(1)
        if not rows:
            return
        done = sum(kw for w, kw in rows if day0 <= w < now.replace(minute=0, second=0, microsecond=0))
        house_w = (self.ov.flow() or {}).get("house") or 0.0
        self.house_so_far = round(done + house_w / 1000 * now.minute / 60, 2)
        self.house_so_far_day = now.date()  # yesterday's total must never count after midnight

    def watch_sign(self, raw_w: float | None, soc: float | None) -> None:
        """Is positive battery power charging or discharging here? Seen from the level going up or down."""
        if raw_w is None or soc is None:
            return
        votes = self.learning.state.setdefault("battery_sign", {"same": 0, "opposite": 0})
        if abs(raw_w) < 200:
            self._sign_prev = None  # idle: start over
            return
        if self._sign_prev is None or (self._sign_prev[0] > 0) != (raw_w > 0):
            self._sign_prev = (raw_w, soc)  # a new run in one direction: remember where the level started
            return
        d = soc - self._sign_prev[1]
        if abs(d) >= 1:  # the level moved a whole percent during the run
            votes["same" if (d > 0) == (raw_w > 0) else "opposite"] += 1
            self._sign_prev = (raw_w, soc)

    def sign_found(self) -> int | None:
        v = self.learning.state.get("battery_sign") or {}
        same, opp = v.get("same", 0), v.get("opposite", 0)
        if opp >= 3 and opp > 3 * same:
            return -1
        if same >= 3 and same > 3 * opp:
            return 1
        return None

    def tou_plan(self) -> dict[str, Any] | None:
        """The own tariff plan, when it's the one in use."""
        from .sources import ZONES

        st = self.ov.settings
        country = (self.ha.config.get("country") or "").upper()
        use = st.get("price_source") == "tou" or (st.get("price_source") in (None, "auto") and country not in ZONES and st.get("tou"))
        return st.get("tou") if use and st.get("tou") else None

    def sell_prices(self) -> dict[datetime, float]:
        """A changing feed-in price (a chosen sensor, or the own tariff plan's feed-in times), with its forecast;
        empty when the price is fixed."""
        e = self.ov.role("sell_price")
        if not e and (plan := self.tou_plan()) and plan.get("sell_periods"):
            from .sources import tou_price

            st = self.ov.settings
            base = plan.get("sell_default")
            if base is None:
                base = float(st.get("sell_price") or 0) if st.get("sell") else 0.0
            sp = {"default": base, "periods": plan["sell_periods"]}
            day0 = datetime.now(self.tz).replace(hour=0, minute=0, second=0, microsecond=0)
            return {t: tou_price(sp, t) for t in (day0 + timedelta(minutes=15 * i) for i in range(2 * 96))}
        if not e or not (s := self.ha.states.get(e)):
            return {}
        from .pricefeed import companions, parse

        now = datetime.now(self.tz)
        out: dict[datetime, float] = {}
        for c in companions(self.ha.states, e):  # Octopus: today's and tomorrow's export rates
            out.update(parse((self.ha.states.get(c) or {}).get("attributes") or {}, self.tz,
                             now.replace(hour=0, minute=0, second=0, microsecond=0)))
        try:
            cur = float(s.get("state"))
            out.setdefault(now.replace(minute=now.minute // 15 * 15, second=0, microsecond=0), cur)
        except (TypeError, ValueError):
            pass
        if out and sorted(out.values())[len(out) // 2] < 0:
            out = {k: -v for k, v in out.items()}  # written as negative when it's paid to you (Amber): earnings are positive here
        return out

    def sell_at(self, prices: dict[datetime, float], when: datetime, fixed: float) -> float:
        if not prices:
            return fixed
        past = [k for k in prices if k <= when]
        return prices[max(past)] if past else prices[min(prices)]

    def ev_in_house(self) -> bool:
        """The user's choice wins; otherwise what was found."""
        chosen = self.ov.settings.get("ev_in_house")
        return bool(chosen) if chosen is not None else bool(self.ev_detected)

    def house_today(self) -> float | None:
        """Today in all: used so far plus the engine's own forecast for the rest of the day - the plan's numbers."""
        rows = (self.result or {}).get("house") or []
        if self.house_so_far is None and not rows:
            return None
        now = datetime.now(self.tz)
        if getattr(self, "house_so_far_day", None) != now.date():
            # Just after midnight, before the next refresh: only this hour's share so far.
            house_w = (self.ov.flow() or {}).get("house") or 0.0
            self.house_so_far, self.house_so_far_day = round(house_w / 1000 * now.minute / 60, 2), now.date()
        rest = sum(r["kwh"] for r in rows if datetime.fromisoformat(r["t"]).date() == now.date())
        rest -= (rows[0]["kwh"] * now.minute / 60) if rows else 0.0  # this hour's gone part is in "so far"
        return round((self.house_so_far or 0.0) + max(0.0, rest), 1)

    async def review(self) -> None:
        """After midnight: yesterday with the real numbers - the engine learns from it (see learning.py)."""
        now = datetime.now(self.tz)
        if now.hour == 0 and now.minute < 10:
            return  # let the statistics for the last hour be written first
        day = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        if self.learning.state.get("reviewed") == day.strftime("%Y-%m-%d"):
            return
        def by_hour(rows: list[tuple[datetime, float]]) -> dict[str, float]:
            return {w.strftime("%Y-%m-%dT%H"): kw for w, kw in rows if w.date() == day.date()}
        house_rows = await self._house_rows(2)  # as the forecast was made (the car taken out)
        house = by_hour(house_rows)
        pv = by_hour(list((await self._hourly_sum(self.ov.role_all("pv_power"), 2)).items())) if self.ov.role_all("pv_power") else {}
        prices = {k: v["price"] for k, v in self.learning._expected(day.strftime("%Y-%m-%d")).items() if v.get("price") is not None}
        soc_start = None
        if self.ov.role("battery_soc"):
            socs = by_hour(await self._hourly_kw(self.ov.role("battery_soc"), 2))
            first = socs.get(day.strftime("%Y-%m-%dT00"))
            soc_start = first * 1000 if first is not None else None  # _hourly_kw divides by 1000 for non-kW units
            soc_start = self.ov.scaled("battery_soc", soc_start) if hasattr(self.ov, "scaled") else soc_start
        if not house:
            return
        report = self.learning.review(day, house, pv, self.settings(), prices, soc_start)
        if report is not None:
            # How well each way hit yesterday - the ML share moves towards what it earned.
            for kind in ("house", "sun"):
                days = (self.house_model.samples // 24) if kind == "house" else self.solar_model.days
                self.mixer.update(kind, report.get(f"{kind}_err_simple"), report.get(f"{kind}_err_ml"), days)
            es, em = self.price_model.score(now)
            if es is not None or em is not None:
                self.mixer.update("price", es, em, self.price_days)
            self.learning.save()
        if report:
            _LOGGER.info("Learned from %s: %s", report["day"], report)

    def _generator(self, now: datetime, f: dict[str, Any], hours: list[tuple[datetime, float, float]]) -> dict[str, Any]:
        """Off-grid: should the generator run now? (see generator.py)"""
        from .generator import GenSettings, decide

        st, b = self.ov.settings, self.settings()
        gs = GenSettings(capacity_kwh=b.capacity_kwh, efficiency=b.efficiency,
                         reserve_soc=float(st.get("reserve_soc") or 30), emergency_soc=float(st.get("emergency_soc") or 20),
                         stop_soc=float(st.get("gen_stop_soc") or 90), charge_kw=float(st.get("gen_charge_kw") or 5),
                         min_run_h=float(st.get("gen_min_run_h") or 2), quiet=frozenset(self.quiet_hours("gen")))
        e = self.ov.role("generator_running") or self.ov.role("generator_switch")
        running = str((self.ha.states.get(e) or {}).get("state")) == "on" if e else False
        if running and not getattr(self, "_gen_since", None):
            self._gen_since = now
        if not running:
            self._gen_since = None
        return decide(now, f.get("soc"), running, self._gen_since, hours, gs)

    def blend_info(self) -> dict[str, Any]:
        """Who decides now, and how well each one hits."""
        return {"house": self.mixer.info("house"), "sun": self.mixer.info("sun"), "price": self.mixer.info("price"),
                "battery": self.batt_learn.info(0.92), "car": self.habits.info(),
                "trained": {"house": self.house_model.samples // 24, "sun": self.solar_model.days, "price": self.price_days}}

    def sources_used(self) -> dict[str, Any]:
        return {"weather": bool(self.weather and self.weather.hours), "own_prices": bool(self.own_prices and not self.ov.role("price")),
                "own_solar": getattr(self.ov, "sun_source", None) == "own", "sun_source": getattr(self.ov, "sun_source", None), "house_model": self.house_model.model is not None,
                "house_error": self.house_model.error, "house_samples": self.house_model.samples}

    def run(self) -> dict[str, Any] | None:
        """Plan from now over the hours with prices."""
        plan = self.ov.plan()
        tz = ZoneInfo(self.ha.config.get("time_zone") or "UTC")
        now = datetime.now(tz)
        start = now.replace(minute=0, second=0, microsecond=0)
        offgrid = bool(self.ov.settings.get("offgrid"))
        if offgrid:
            for h in plan["hours"]:
                h.setdefault("price", 0.0)  # no grid, no prices: the battery and the generator are all there is
        rows = [h for h in plan["hours"] if "price" in h and datetime.fromisoformat(h["t"]) >= start]
        if not rows:
            return None
        times = [datetime.fromisoformat(h["t"]) for h in rows]
        from .blend import Mixer

        w = self.weather if self.weather and self.weather.hours else None
        simple = house_forecast(self.profile, times) if self.profile else [h.get("house", 0.6) for h in rows]
        ml = self.house_model.predict(times, w) or [None] * len(times)
        hw = self.mixer.share("house")
        house = [Mixer.mix(s, m, hw) for s, m in zip(simple, ml)]
        st = self.ov.settings
        sell = float(st.get("sell_price") or 0) if st.get("sell") else 0.0  # what exported power earns
        sells = self.sell_prices()  # a changing feed-in price, when one is chosen
        # What it has learned: the sun forecast's usual error (cloudy/clear) and a margin on the house in the dear hours.
        L = self.learning
        clouds = [((self.weather.at(t) or {}).get("cloud") if self.weather else None) for t in times]
        dear = sorted(r["price"] for r in rows)[int(len(rows) * 0.75)] if len(rows) > 3 else None
        sun_simple = [L.sun(r.get("sun", 0.0), clouds[i]) for i, r in enumerate(rows)]
        sun_ml = self.solar_model.predict(times, w) if w else {}
        sw = self.mixer.share("sun")
        sun = [Mixer.mix(s, sun_ml.get(t), sw) for s, t in zip(sun_simple, times)]
        hours = [Hour(t, r["price"], self.sell_at(sells, t, sell), house[i] + (L.margin if dear is not None and r["price"] >= dear else 0.0), sun[i])
                 for i, (t, r) in enumerate(zip(times, rows))]
        L.expect([{"t": times[0].isoformat(), "house": house[0], "sun": hours[0].sun, "price": rows[0]["price"], "cloud": clouds[0],
                   "house_s": simple[0], "house_m": ml[0], "sun_s": sun_simple[0], "sun_m": sun_ml.get(times[0])}])
        # Prices per quarter (or half) hour where the market has them: plan in those slots, so the battery and
        # the car use the cheapest quarters inside an hour too. House and sun are spread evenly over the hour.
        hours = split_slots(hours, getattr(self.ov, "fine_prices", None) or {}, now, sells)
        slot_min = round(hours[0].length * 60) if hours else 60
        f = self.ov.flow()
        result: dict[str, Any] = {"at": now.isoformat(), "house": [{"t": t.isoformat(), "kwh": k} for t, k in zip(times, house)],
                                  "style": st.get("style") or "cheapest"}
        car_plan = self._car(hours, now, f, skip=set()) if (st.get("style") == "car_first") else None
        if car_plan:
            charger = float(st.get("charger_kw") or 7.4)
            for h in hours:
                if h.start in car_plan["set"]:
                    h.house += charger * h.length  # the car gets the sun first: what's left goes to the battery
        if offgrid:
            result["generator"] = self._generator(now, f, [(t, house[i], sun[i]) for i, t in enumerate(times)])
        if f["soc"] is not None and not offgrid:
            b = self.settings()
            # The car's cheap charging hours: the house battery doesn't empty itself into the car then.
            pre = car_plan or (self._car(hours, now, f, set()) if f.get("plug") else None)
            if pre and pre.get("set"):
                from dataclasses import replace

                b = replace(b, no_discharge=frozenset(pre["set"]))
            if st.get("battery_no_export_cheap"):
                from dataclasses import replace

                b = replace(b, no_export=cheap_slots(hours))  # no selling while power is cheap - only charging
            end_value = end_price(hours, b) * L.end_factor
            p = plan_battery(hours, f["soc"], b, end_value=end_value)
            # A daily cap on paid feed-in (15 kWh a day, say): what is sold past it earns nothing - the best-paid
            # slots keep the pay, the plan is made again without pay in the rest.
            cap = (self.tou_plan() or {}).get("sell_cap_kwh")
            for _ in range(3):
                over = over_cap(hours, p, float(cap)) if cap else []
                if not over:
                    break
                for h in over:
                    h.sell = 0.0
                p = plan_battery(hours, f["soc"], b, end_value=end_value)
            # The target: where the current action leads (not just the end of this quarter).
            run = 0
            while run + 1 < len(p.steps) and p.steps[run + 1].action == p.steps[0].action:
                run += 1
            result["battery"] = {
                "steps": [{"t": s.start.isoformat(), "action": s.action, "soc": s.soc_end, "grid": s.grid_kwh} for s in p.steps],
                "slot_min": slot_min,
                "now": ACTION_KIND[p.steps[0].action] if p.steps else "hold", "target": p.steps[run].soc_end if p.steps else None,
                "cost": p.cost, "cost_without": p.cost_without, "saving": p.saving, "capacity": b.capacity_kwh,
            }
        try:
            from . import checks

            self.checks = checks.run(self, hours, self.settings(), p if f["soc"] is not None and not offgrid else None,
                                     end_value if f["soc"] is not None and not offgrid else 0.0)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Self-check failed", exc_info=True)
        if car_plan is None:
            skip = set()
            if st.get("style") == "battery_first" and result.get("battery"):
                skip = {datetime.fromisoformat(x["t"]) for x in result["battery"]["steps"] if x["action"] == "charge_sun"}
            car_plan = self._car(hours, now, f, skip)
        if car_plan:
            result["car"] = {"hours": car_plan["hours"], "need_kwh": car_plan["need"], "slot_min": slot_min}
        result["cars"] = self._more_cars(hours, now, f, car_plan, slot_min)
        try:
            result["things"] = self._things(hours, now, result, car_plan)
        except Exception:  # noqa: BLE001 - the small things must never stop the plan
            _LOGGER.debug("Things plan failed", exc_info=True)
        try:
            self._ghost_plans(hours, now, f, slot_min)
        except Exception:  # noqa: BLE001 - a comparison must never stop the plan
            _LOGGER.debug("Shadow car plan failed", exc_info=True)
        self.result = result
        self._compare()
        return result

    def _things(self, hours: list[Hour], now: datetime, result: dict[str, Any], car_plan: dict[str, Any] | None) -> list[dict[str, Any]]:
        """The small things, after the battery and the cars: only the sun the plan would sell, and the fuse with the cars."""
        st = self.ov.settings
        if not st.get("things"):
            return []
        steps = {datetime.fromisoformat(x["t"]): x for x in ((result.get("battery") or {}).get("steps") or [])}
        load: dict[datetime, float] = {}
        if car_plan:
            for t in car_plan.get("set") or []:
                load[t] = load.get(t, 0.0) + float(st.get("charger_kw") or 7.4)
        from . import chargers

        for c, p in zip(chargers.extras(st), result.get("cars") or []):
            for x in p.get("hours") or []:
                t = datetime.fromisoformat(x)
                load[t] = load.get(t, 0.0) + float(c.get("charger_kw") or 7.4)
        left = {}
        for h in hours:
            s = steps.get(h.start)
            spare = -float(s["grid"]) if s and s.get("grid") is not None else h.sun - h.house  # what the plan would sell
            left[h.start] = max(0.0, spare - load.get(h.start, 0.0) * h.length)
        limit = float(st["import_limit_kw"]) if st.get("import_limit_kw") else None
        return self.things.plan(st, hours, now, left, load, limit)

    def _car(self, hours: list[Hour], now: datetime, f: dict[str, Any], skip: set) -> dict[str, Any] | None:
        ev, st = self.ov.ev(), self.ov.settings
        if ev is None or not f.get("plug"):
            return None
        # What the user set wins; otherwise the car's learned habits (when it leaves, how much it takes).
        cap = float(ev.get("cap")) if self.ov.role("ev_cap") and ev.get("cap") else self.habits.need(float(ev.get("cap") or st.get("ev_need_kwh") or 20))
        need = cap - float(ev.get("session_kwh") or 0)
        if ev.get("soc") is not None:
            # The car says how full it is: what's missing up to the target (100 % before a long trip).
            from . import evsoc

            need = evsoc.need_kwh(ev["soc"], ev["target"], ev["car_kwh"])
        ready = None
        if ev.get("ready") and ev["ready"] != "00:00:00":
            hh, mm = (int(x) for x in str(ev["ready"]).split(":")[:2])
            ready = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if ready <= now:
                ready += timedelta(days=1)
        else:
            for ahead in (0, 1):
                day = now + timedelta(days=ahead)
                if (lv := self.habits.leave(day.weekday())) is not None:
                    cand = day.replace(hour=lv[0], minute=lv[1], second=0, microsecond=0)
                    if cand > now:
                        ready = cand
                        break
        if quiet := self.quiet_hours("car"):
            skip = skip | {h.start for h in hours if h.start.hour in quiet}
        kw = float(st.get("charger_kw") or 7.4)
        chosen = None
        if pt := self.power_tariff():
            # Power tariff: charge beside the peaks when that still gets the car full - else as usual.
            over = {h.start for h in hours if h.house / h.length + kw > pt["limit_kw"]}
            chosen = plan_car(hours, max(0.0, need), kw, ready, now, solar_only=st.get("ev_mode") == "solar", skip=skip | over)
            if sum(h.length for h in hours if h.start in set(chosen)) * kw < max(0.0, need) - 0.5:
                chosen = None
        if chosen is None:
            chosen = plan_car(hours, max(0.0, need), kw, ready, now, solar_only=st.get("ev_mode") == "solar", skip=skip)
        return {"hours": [t.isoformat() for t in chosen], "set": set(chosen), "need": round(max(0.0, need), 1)}

    def _ghost_plans(self, hours: list[Hour], now: datetime, f: dict[str, Any], slot_min: int) -> None:
        """A charger in shadow, just plugged in: the charge Energy Pilot would make, kept for comparison."""
        from . import chargers

        ctl = getattr(self.ov, "controller", None)
        st = self.ov.settings
        quiet = self.quiet_hours("car")
        prices = {h.start: h.price for h in hours}
        parts = [("car", None)] + [(f"car{i + 2}", c) for i, c in enumerate(chargers.extras(st))]
        for part, c in parts:
            if (ctl and ctl.mode(part) == "control") or not self.ghosts.wants_plan(part):
                continue
            if c is None:
                ev = self.ov.ev() or {}
                kw = float(st.get("charger_kw") or 7.4)
                need = self.ghosts.need(part, self.habits.need(float(st.get("ev_need_kwh") or 20)))
                if ev.get("soc") is not None and ev.get("car_kwh"):
                    from . import evsoc

                    need = evsoc.need_kwh(ev["soc"], ev["target"], ev["car_kwh"])
                ready = None
                if ev.get("ready") and ev["ready"] != "00:00:00":
                    hh, mm = (int(x) for x in str(ev["ready"]).split(":")[:2])
                    ready = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                    ready += timedelta(days=1) if ready <= now else timedelta(0)
                mode = st.get("ev_mode")
            else:
                kw = float(c.get("charger_kw") or 7.4)
                need = self.ghosts.need(part, float(c.get("need_kwh") or 20))
                ready, mode = chargers.ready_at(c, now), c.get("mode")
            skip = {h.start for h in hours if h.start.hour in quiet}
            chosen = plan_car(hours, max(0.0, need), kw, ready, now, solar_only=mode == "solar", skip=skip)
            self.ghosts.set_plan(part, chosen, max(0.0, need), prices, kw, slot_min / 60)

    def _more_cars(self, hours: list[Hour], now: datetime, f: dict[str, Any], car_plan: dict[str, Any] | None,
                   slot_min: int) -> list[dict[str, Any]] | None:
        """The other chargers: each car planned on its own - the cars before it and the main fuse taken into account."""
        from . import chargers

        more = chargers.extras(self.ov.settings)
        if not more:
            return None
        st = self.ov.settings
        limit = float(st["import_limit_kw"]) if st.get("import_limit_kw") else None
        load = {h.start: 0.0 for h in hours}  # what the cars already planned draw in each slot (kW)
        if car_plan:
            for t in car_plan["set"]:
                load[t] = load.get(t, 0.0) + float(st.get("charger_kw") or 7.4)
        quiet = self.quiet_hours("car")
        out = []
        for c, now_c in zip(more, f.get("cars") or [{}] * len(more)):
            kw = float(c.get("charger_kw") or 7.4)
            entry = {"name": c.get("name") or "", "plug": bool(now_c.get("plug")), "hours": [], "need_kwh": 0.0, "slot_min": slot_min}
            if now_c.get("plug"):
                need = max(0.0, float(c.get("need_kwh") or 20) - float(now_c.get("session_kwh") or 0))
                if c.get("now"):
                    ready = now + timedelta(hours=need / kw + 0.25)  # charge now: straight away, whatever the price
                else:
                    ready = chargers.ready_at(c, now)
                skip = {h.start for h in hours if h.start.hour in quiet}
                if limit is not None:  # never more than the main fuse: house + the other cars + this one
                    skip |= {h.start for h in hours if h.house / h.length + load.get(h.start, 0.0) + kw > limit + 1e-9}
                chosen = plan_car(hours, need, kw, ready, now, solar_only=c.get("mode") == "solar", skip=skip)
                for t in chosen:
                    load[t] = load.get(t, 0.0) + kw
                entry.update(hours=[t.isoformat() for t in chosen], need_kwh=round(need, 1))
            out.append(entry)
        return out

    def _compare(self) -> None:
        """How often the engine agrees with the system that controls today (when there is one)."""
        mine = ((self.result or {}).get("battery") or {}).get("now")
        theirs = self.ov.other_decision("en")
        if mine and theirs and self.ov.role("battery_plan"):
            self.agree["checks"] += 1
            self.agree["same"] += int(mine == theirs["kind"])

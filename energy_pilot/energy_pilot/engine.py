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
import time
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
    pct_step = step_pct / 100 * b.capacity_kwh  # kWh between two levels
    best = [[INF] * m for _ in range(n + 1)]
    choice: list[list[tuple[int, str, float, float]]] = [[(0, "hold", 0.0, 0.0)] * m for _ in range(n)]
    for j, lv in enumerate(levels):
        best[n][j] = -(kwh(lv) - kwh(b.min_soc)) * end_value
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
                    if delta / eff > b.max_charge_kw * h.length + 1e-9:
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
                    if -delta > b.max_discharge_kw * h.length + 1e-9:
                        continue
                    need = max(0.0, h.house - h.sun)
                    if out > need + 1e-9:
                        continue  # no exporting from the battery
                    grid = h.house - h.sun - out
                    action = "discharge"
                else:
                    grid = h.house - h.sun
                    action = "hold"
                if b.import_limit_kw is not None and grid > b.import_limit_kw * h.length + 1e-9 and delta > 0:
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


def split_slots(hours: list[Hour], prices: dict[datetime, float], now: datetime) -> list[Hour]:
    """Hours split into the market's price slots, each with its own price; the slot now is scaled to what's left."""
    res = resolution(prices, now) if prices else 60
    k = 60 // res
    out = []
    for h in hours:
        for i in range(k):
            start = h.start + timedelta(minutes=i * res)
            if start + timedelta(minutes=res) <= now:
                continue  # already gone
            price = prices.get(start, h.price) if k > 1 else h.price
            out.append(Hour(start, price, h.sell, h.house / k, h.sun / k, res / 60))
    if out and out[0].start < now:
        part = 1 - (now - out[0].start).total_seconds() / (out[0].length * 3600)
        out[0].house *= part
        out[0].sun *= part
    return out


# ---------- running it ----------

ACTION_KIND = {"discharge": "discharge", "charge_sun": "charge", "charge_grid": "grid", "hold": "hold"}


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
        self.batt_learn = BatteryLearner(self.learning.state)
        self.weather: Any = None
        self.house_model = HouseModel()
        self.solar_factors: dict[int, float] = {}
        self.own_prices: list[dict[str, Any]] = []
        self.own_solar: dict[datetime, float] = {}
        self._prices_at = 0.0
        self.profile: dict[tuple[bool, int], float] = {}
        self.profile_at: datetime | None = None
        self.result: dict[str, Any] | None = None
        self.agree = {"checks": 0, "same": 0}
        self.house_so_far: float | None = None  # kWh the house has used today, from the statistics
        self.ev_detected: bool | None = None  # is the car in the house's use? (see evsplit.py)

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
            quiet=frozenset(self.quiet_hours("battery")),
            efficiency=self.batt_learn.efficiency(0.92),  # the datasheet's, until it has seen the real one
        )

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
        if e := self.ov.role("house_power"):
            rows = await self._hourly_kw(e, 60)
            if rows and (ev_e := self.ov.role("ev_power")):
                from . import evsplit

                ev_rows = await self._hourly_kw(ev_e, 60)
                self.ev_detected = evsplit.detect(rows, ev_rows)
                if self.ev_in_house():
                    rows = evsplit.subtract(rows, ev_rows)  # the car is planned on its own
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
        if self.solar_factors and self.weather and not self.ov.role("solar_today"):
            start = datetime.now(self.tz).replace(minute=0, second=0, microsecond=0)
            self.own_solar = solar_forecast(self.solar_factors, self.weather, [start + timedelta(hours=i) for i in range(48)])

    async def refresh_house_today(self) -> None:
        """What the house has used so far today (whole hours from the statistics, plus this hour's share)."""
        if not (e := self.ov.role("house_power")):
            return
        now = datetime.now(self.tz)
        day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
        rows = await self._hourly_kw(e, 1)
        if self.ev_in_house() and (ev_e := self.ov.role("ev_power")):
            from . import evsplit

            rows = evsplit.subtract(rows, await self._hourly_kw(ev_e, 1))
        done = sum(kw for w, kw in rows if day0 <= w < now.replace(minute=0, second=0, microsecond=0))
        house_w = (self.ov.flow() or {}).get("house") or 0.0
        self.house_so_far = round(done + house_w / 1000 * now.minute / 60, 2)

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
        house_rows = await self._hourly_kw(self.ov.role("house_power"), 2) if self.ov.role("house_power") else []
        if house_rows and self.ev_in_house() and (ev_e := self.ov.role("ev_power")):
            from . import evsplit

            house_rows = evsplit.subtract(house_rows, await self._hourly_kw(ev_e, 2))  # as the forecast was made
        house = by_hour(house_rows)
        pv = by_hour(list((await self._hourly_sum(self.ov.role_all("pv_power"), 2)).items())) if self.ov.role_all("pv_power") else {}
        prices = {k: v["price"] for k, v in self.learning._expected(day.strftime("%Y-%m-%d")).items() if v.get("price") is not None}
        soc_start = None
        if self.ov.role("battery_soc"):
            socs = by_hour(await self._hourly_kw(self.ov.role("battery_soc"), 2))
            first = socs.get(day.strftime("%Y-%m-%dT00"))
            soc_start = first * 1000 if first is not None else None  # _hourly_kw divides by 1000 for non-kW units
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

    def blend_info(self) -> dict[str, Any]:
        """Who decides now, and how well each one hits."""
        return {"house": self.mixer.info("house"), "sun": self.mixer.info("sun"), "price": self.mixer.info("price"),
                "battery": self.batt_learn.info(0.92), "car": self.habits.info(),
                "trained": {"house": self.house_model.samples // 24, "sun": self.solar_model.days, "price": self.price_days}}

    def sources_used(self) -> dict[str, Any]:
        return {"weather": bool(self.weather and self.weather.hours), "own_prices": bool(self.own_prices and not self.ov.role("price")),
                "own_solar": bool(self.own_solar and not self.ov.role("solar_today")), "house_model": self.house_model.model is not None,
                "house_error": self.house_model.error, "house_samples": self.house_model.samples}

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
        from .blend import Mixer

        w = self.weather if self.weather and self.weather.hours else None
        simple = house_forecast(self.profile, times) if self.profile else [h.get("house", 0.6) for h in rows]
        ml = self.house_model.predict(times, w) or [None] * len(times)
        hw = self.mixer.share("house")
        house = [Mixer.mix(s, m, hw) for s, m in zip(simple, ml)]
        st = self.ov.settings
        sell = float(st.get("sell_price") or 0) if st.get("sell") else 0.0  # what exported power earns
        # What it has learned: the sun forecast's usual error (cloudy/clear) and a margin on the house in the dear hours.
        L = self.learning
        clouds = [((self.weather.at(t) or {}).get("cloud") if self.weather else None) for t in times]
        dear = sorted(r["price"] for r in rows)[int(len(rows) * 0.75)] if len(rows) > 3 else None
        sun_simple = [L.sun(r.get("sun", 0.0), clouds[i]) for i, r in enumerate(rows)]
        sun_ml = self.solar_model.predict(times, w) if w else {}
        sw = self.mixer.share("sun")
        sun = [Mixer.mix(s, sun_ml.get(t), sw) for s, t in zip(sun_simple, times)]
        hours = [Hour(t, r["price"], sell, house[i] + (L.margin if dear is not None and r["price"] >= dear else 0.0), sun[i])
                 for i, (t, r) in enumerate(zip(times, rows))]
        L.expect([{"t": times[0].isoformat(), "house": house[0], "sun": hours[0].sun, "price": rows[0]["price"], "cloud": clouds[0],
                   "house_s": simple[0], "house_m": ml[0], "sun_s": sun_simple[0], "sun_m": sun_ml.get(times[0])}])
        # Prices per quarter (or half) hour where the market has them: plan in those slots, so the battery and
        # the car use the cheapest quarters inside an hour too. House and sun are spread evenly over the hour.
        hours = split_slots(hours, getattr(self.ov, "fine_prices", None) or {}, now)
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
        if f["soc"] is not None:
            b = self.settings()
            end_value = median(h.price for h in hours) * math.sqrt(b.efficiency) * L.end_factor
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
        if car_plan is None:
            skip = set()
            if st.get("style") == "battery_first" and result.get("battery"):
                skip = {datetime.fromisoformat(x["t"]) for x in result["battery"]["steps"] if x["action"] == "charge_sun"}
            car_plan = self._car(hours, now, f, skip)
        if car_plan:
            result["car"] = {"hours": car_plan["hours"], "need_kwh": car_plan["need"], "slot_min": slot_min}
        self.result = result
        self._compare()
        return result

    def _car(self, hours: list[Hour], now: datetime, f: dict[str, Any], skip: set) -> dict[str, Any] | None:
        ev, st = self.ov.ev(), self.ov.settings
        if ev is None or not f.get("plug"):
            return None
        # What the user set wins; otherwise the car's learned habits (when it leaves, how much it takes).
        cap = float(ev.get("cap")) if self.ov.role("ev_cap") and ev.get("cap") else self.habits.need(float(ev.get("cap") or st.get("ev_need_kwh") or 20))
        need = cap - float(ev.get("session_kwh") or 0)
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

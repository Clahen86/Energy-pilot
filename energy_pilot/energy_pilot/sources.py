"""What the engine can find out by itself, so a home needs nothing but its inverter or battery in Home Assistant:

- holidays (Danish, computed - Easter and all that follows from it)
- weather and sunlight for the home's location (Open-Meteo, free, no key) - also the past weeks, to learn from
- spot prices (Energi Data Service, free) with tax, grid tariff and VAT on top - the user picks the area and can
  adjust the tariff
- its own solar forecast: sunlight from the weather service times what this system makes of it (learned per hour
  of the day from its own production, so the roof's direction and shade are in it)
- a learned forecast of the house's use (gradient boosting on hour, weekday, holiday and temperature; recent weeks
  weigh most) - falls back to a simple hourly profile when there's little history

A source the home already has (Strømligning, Solcast …) is used instead: it is usually better.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
import math
import time
from typing import Any
from zoneinfo import ZoneInfo

_LOGGER = logging.getLogger(__name__)
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
EDS = "https://api.energidataservice.dk/dataset/DayAheadPrices"


# ---------- holidays ----------

def easter(year: int) -> date:
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def holidays_dk(year: int) -> set[date]:
    e = easter(year)
    return {date(year, 1, 1), e - timedelta(days=3), e - timedelta(days=2), e, e + timedelta(days=1),
            e + timedelta(days=39), e + timedelta(days=49), e + timedelta(days=50), date(year, 6, 5),
            date(year, 12, 24), date(year, 12, 25), date(year, 12, 26), date(year, 12, 31)}


COUNTRY = "DK"  # set from Home Assistant's country at start


def is_day_off(d: date) -> bool:
    if d.weekday() >= 5:
        return True
    if COUNTRY == "DK":
        return d in holidays_dk(d.year)
    try:
        import holidays

        return d in holidays.country_holidays(COUNTRY, years=d.year)
    except Exception:  # noqa: BLE001 - unknown country: weekends only
        return False


# ---------- weather ----------

class Weather:
    """Hourly temperature, cloud cover and sunlight (W/m²): the past weeks and the next two days."""

    def __init__(self, session: Any, lat: float, lon: float, tz: ZoneInfo) -> None:
        self.session, self.lat, self.lon, self.tz = session, lat, lon, tz
        self.hours: dict[datetime, dict[str, float]] = {}
        self._at = 0.0

    async def refresh(self, past_days: int = 45) -> None:
        if time.time() - self._at < 3600 and self.hours:
            return
        params = {"latitude": f"{self.lat:.3f}", "longitude": f"{self.lon:.3f}", "timezone": str(self.tz),
                  "hourly": "temperature_2m,cloud_cover,shortwave_radiation", "past_days": str(past_days), "forecast_days": "2"}
        async with self.session.get(OPEN_METEO, params=params, timeout=30) as resp:
            resp.raise_for_status()
            data = await resp.json()
        h = data.get("hourly") or {}
        out = {}
        for i, t in enumerate(h.get("time") or []):
            when = datetime.fromisoformat(t).replace(tzinfo=self.tz)
            out[when] = {"temp": h["temperature_2m"][i], "cloud": h["cloud_cover"][i], "sun": h["shortwave_radiation"][i]}
        self.hours, self._at = out, time.time()

    def at(self, when: datetime) -> dict[str, float] | None:
        return self.hours.get(when.astimezone(self.tz).replace(minute=0, second=0, microsecond=0))


# ---------- prices ----------

# Typical Danish grid tariff (kr/kWh excl. VAT) by hour - low at night, peak 17-21. Adjustable in the settings.
DEFAULT_TARIFF = {"low": 0.115, "high": 0.346, "peak": 1.038}  # Radius 2026, roughly - the user can adjust
TARIFF_HOURS = {h: ("low" if h < 6 else "peak" if 17 <= h < 21 else "high") for h in range(24)}


# Bidding zones per country (day-ahead prices), and VAT on electricity.
ZONES = {
    "DK": ["DK1", "DK2"], "SE": ["SE1", "SE2", "SE3", "SE4"], "NO": ["NO1", "NO2", "NO3", "NO4", "NO5"], "FI": ["FI"],
    "DE": ["DE-LU"], "LU": ["DE-LU"], "NL": ["NL"], "BE": ["BE"], "AT": ["AT"], "FR": ["FR"], "PL": ["PL"], "CH": ["CH"],
    "CZ": ["CZ"], "SK": ["SK"], "SI": ["SI"], "HU": ["HU"], "HR": ["HR"], "RO": ["RO"], "BG": ["BG"], "GR": ["GR"],
    "ES": ["ES"], "PT": ["PT"], "EE": ["EE"], "LV": ["LV"], "LT": ["LT"],
    "IT": ["IT-North", "IT-Centre-North", "IT-Centre-South", "IT-South", "IT-Sicily", "IT-Sardinia"],
}
VAT = {"DK": 0.25, "SE": 0.25, "NO": 0.25, "FI": 0.255, "DE": 0.19, "LU": 0.08, "NL": 0.21, "BE": 0.06, "AT": 0.20,
       "FR": 0.20, "PL": 0.23, "CH": 0.081, "CZ": 0.21, "SK": 0.23, "SI": 0.22, "HU": 0.27, "HR": 0.13, "RO": 0.19,
       "BG": 0.20, "GR": 0.06, "ES": 0.21, "PT": 0.06, "EE": 0.24, "LV": 0.21, "LT": 0.21, "IT": 0.10}
ENERGY_CHARTS = "https://api.energy-charts.info/price"
FX = "https://api.frankfurter.dev/v1/latest"
_fx: dict[str, Any] = {"at": 0.0, "rates": {}}


def price_area(lat: float, lon: float, country: str | None = None) -> str:
    """The home's bidding zone - a guess the user can change."""
    country = (country or COUNTRY or "DK").upper()
    if country == "DK":
        return "DK2" if lon >= 11.0 else "DK1"
    if country == "SE":
        return "SE1" if lat >= 66 else "SE2" if lat >= 61.5 else "SE3" if lat >= 57.2 else "SE4"
    if country == "NO":
        return "NO4" if lat >= 65 else "NO3" if lat >= 62.5 else "NO5" if lon <= 7.5 and lat >= 59.8 else "NO2" if lon <= 9 else "NO1"
    return (ZONES.get(country) or ["DE-LU"])[0]


def consumer_price(spot_mwh: float, hour: int, s: dict[str, Any], country: str | None = None) -> float:
    """What a kWh costs at home: spot + grid tariff + taxes + markup, with VAT. Spot in the local currency per MWh.
    Denmark has its tariff model built in; elsewhere the user says what is added (default: VAT only)."""
    country = (country or COUNTRY or "DK").upper()
    vat = float(s.get("vat", VAT.get(country, 0.2)))
    if country == "DK":
        tariff = {**DEFAULT_TARIFF, **(s.get("tariff") or {})}
        extra = tariff[TARIFF_HOURS[hour]] + float(s.get("system_tariff", 0.072)) + float(s.get("elafgift", 0.008)) + float(s.get("markup", 0.012))
    else:
        tariff = {"low": 0.0, "high": 0.0, "peak": 0.0, **(s.get("tariff") or {})}
        extra = tariff[TARIFF_HOURS[hour]] + float(s.get("markup", 0.0))
    return round((spot_mwh / 1000 + extra) * (1 + vat), 4)


def country_of(area: str) -> str:
    """The country a bidding zone belongs to ("SE3" -> "SE", "DE-LU" -> "DE", "IT-North" -> "IT")."""
    return area[:2].upper()


async def _rate(session: Any, currency: str) -> float:
    """EUR -> the home's currency (ECB rates, once a day)."""
    if currency == "EUR":
        return 1.0
    if time.time() - _fx["at"] > 86400 or currency not in _fx["rates"]:
        async with session.get(FX, params={"base": "EUR"}, timeout=20) as resp:
            resp.raise_for_status()
            _fx["rates"], _fx["at"] = (await resp.json()).get("rates") or {}, time.time()
    return float(_fx["rates"][currency])


async def fetch_prices(session: Any, area: str, tz: ZoneInfo, s: dict[str, Any], currency: str = "DKK") -> list[dict[str, Any]]:
    """[{start, end, price}] for today and tomorrow (as far as known), like Strømligning's "prices".
    Danish zones from Energi Data Service (in DKK), all others from energy-charts.info (EUR, converted)."""
    if not area.startswith("DK"):
        rate = await _rate(session, currency)
        async with session.get(ENERGY_CHARTS, params={"bzn": area}, timeout=30) as resp:
            resp.raise_for_status()
            data = await resp.json()
        out = []
        times, prices = data.get("unix_seconds") or [], data.get("price") or []
        step = (times[1] - times[0]) if len(times) > 1 else 3600
        for ts, eur in zip(times, prices):
            if eur is None:
                continue
            t = datetime.fromtimestamp(ts, tz)
            out.append({"start": t.isoformat(), "end": (t + timedelta(seconds=step)).isoformat(),
                        "price": consumer_price(eur * rate, t.hour, s, country_of(area))})
        return out
    start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    params = {"start": start.strftime("%Y-%m-%dT%H:%M"), "end": (start + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"),
              "filter": f'{{"PriceArea":["{area}"]}}', "sort": "TimeDK asc", "limit": "400"}
    async with session.get(EDS, params=params, timeout=30) as resp:
        resp.raise_for_status()
        data = await resp.json()
    out = []
    for r in data.get("records") or []:
        t = datetime.fromisoformat(r["TimeDK"]).replace(tzinfo=ZoneInfo("Europe/Copenhagen")).astimezone(tz)
        spot = r.get("DayAheadPriceDKK")
        if spot is None:
            continue
        out.append({"start": t.isoformat(), "end": (t + timedelta(minutes=15)).isoformat(), "price": consumer_price(spot, t.hour, s, "DK")})
    return out


# ---------- own solar forecast ----------

def learn_solar(pv_kw_by_hour: dict[datetime, float], weather: Weather) -> dict[int, float]:
    """kWh per (kWh/m² of sunlight) for each hour of the day - the system's size, direction and shade in one."""
    num: dict[int, float] = {}
    den: dict[int, float] = {}
    for when, kw in pv_kw_by_hour.items():
        w = weather.at(when)
        if not w or w["sun"] is None or w["sun"] < 20 or kw is None:
            continue
        sun_kwh = w["sun"] / 1000
        num[when.hour] = num.get(when.hour, 0.0) + kw * sun_kwh
        den[when.hour] = den.get(when.hour, 0.0) + sun_kwh * sun_kwh
    return {h: num[h] / den[h] for h in num if den[h] > 0.01}


def solar_forecast(factors: dict[int, float], weather: Weather, hours: list[datetime]) -> dict[datetime, float]:
    out = {}
    overall = sorted(factors.values())[len(factors) // 2] if factors else None
    for h in hours:
        w = weather.at(h)
        if not w or w["sun"] is None:
            continue
        f = factors.get(h.hour, overall)
        if f is not None:
            out[h] = round(max(0.0, f * w["sun"] / 1000), 3)
    return out


# ---------- learned house forecast ----------

class HouseModel:
    """kWh per hour from hour, weekday, day off and temperature - recent weeks weigh most."""

    def __init__(self) -> None:
        self.model: Any = None
        self.samples = 0
        self.error: float | None = None  # mean absolute error on the last week, kWh

    @staticmethod
    def features(when: datetime, temp: float | None) -> list[float]:
        return [when.hour, math.sin(when.hour / 24 * 2 * math.pi), math.cos(when.hour / 24 * 2 * math.pi),
                when.weekday(), float(is_day_off(when.date())), temp if temp is not None else 10.0]

    def train(self, rows: list[tuple[datetime, float]], weather: Weather | None, now: datetime) -> bool:
        if len(rows) < 24 * 7:
            return False
        try:
            from sklearn.ensemble import GradientBoostingRegressor
        except ImportError:
            return False
        X, y, w = [], [], []
        for when, kw in rows:
            if kw is None or kw < 0 or kw > 50:
                continue
            t = (weather.at(when) or {}).get("temp") if weather else None
            X.append(self.features(when, t))
            y.append(kw)
            w.append(0.5 ** (max(0.0, (now - when).total_seconds() / 86400) / 14))
        if len(X) < 24 * 7:
            return False
        cut = max(1, len(X) - 24 * 7)
        model = GradientBoostingRegressor(n_estimators=150, max_depth=3, learning_rate=0.08, subsample=0.9)
        model.fit(X[:cut], y[:cut], sample_weight=w[:cut])
        if cut < len(X):
            pred = model.predict(X[cut:])
            self.error = round(sum(abs(p - a) for p, a in zip(pred, y[cut:])) / len(pred), 3)
        model.fit(X, y, sample_weight=w)  # then on everything
        self.model, self.samples = model, len(X)
        return True

    def predict(self, hours: list[datetime], weather: Weather | None) -> list[float] | None:
        if self.model is None:
            return None
        X = [self.features(h, (weather.at(h) or {}).get("temp") if weather else None) for h in hours]
        return [round(max(0.0, float(v)), 3) for v in self.model.predict(X)]


# ---------- own tariff plan (time of use) ----------

# Examples to start from - the user checks them against the bill (prices change).
TOU_PRESETS = {
    "day_night": {"name": "Dag/nat", "default": 0.30, "periods": [{"name": "Nat", "price": 0.20, "from": "23:00", "to": "07:00", "days": "all"}]},
    "peak_17_21": {"name": "Spidslast 17-21", "default": 0.30, "periods": [{"name": "Spids", "price": 0.55, "from": "17:00", "to": "21:00", "days": "all"}]},
    "pge_etou_c": {"name": "PG&E E-TOU-C (US)", "default": 0.42, "currency": "USD",
                   "periods": [{"name": "Peak", "price": 0.52, "from": "16:00", "to": "21:00", "days": "all"}]},
    "sce_tou_d_4_9": {"name": "SCE TOU-D-4-9PM (US)", "default": 0.33, "currency": "USD",
                      "periods": [{"name": "On-peak", "price": 0.55, "from": "16:00", "to": "21:00", "days": "weekdays"},
                                  {"name": "Mid-peak", "price": 0.43, "from": "16:00", "to": "21:00", "days": "weekends"}]},
    "economy7": {"name": "Economy 7 (UK)", "default": 0.29, "currency": "GBP",
                 "periods": [{"name": "Night", "price": 0.14, "from": "00:30", "to": "07:30", "days": "all"}]},
}


def _minutes(text: str) -> int:
    h, m = (int(x) for x in str(text).split(":")[:2])
    return h * 60 + m


def tou_price(plan: dict[str, Any], when: datetime) -> float:
    """The price at a moment from a plan: the first period that covers it, else the default."""
    m = when.hour * 60 + when.minute
    weekend = is_day_off(when.date())
    for p in plan.get("periods") or []:
        days = p.get("days", "all")
        if (days == "weekdays" and weekend) or (days == "weekends" and not weekend):
            continue
        months = p.get("months")
        if months and when.month not in months:
            continue
        a, b = _minutes(p.get("from", "00:00")), _minutes(p.get("to", "00:00"))
        if (a <= m < b) if a < b else (m >= a or m < b):
            return float(p["price"])
    return float(plan.get("default", 0))


def tou_prices(plan: dict[str, Any], tz: ZoneInfo) -> list[dict[str, Any]]:
    """Today and tomorrow in 15-minute steps, like a price sensor's "prices"."""
    start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    for i in range(2 * 96):
        t = start + timedelta(minutes=15 * i)
        out.append({"start": t.isoformat(), "end": (t + timedelta(minutes=15)).isoformat(), "price": round(tou_price(plan, t), 4)})
    return out

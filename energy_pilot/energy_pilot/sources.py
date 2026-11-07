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


def is_day_off(d: date) -> bool:
    return d.weekday() >= 5 or d in holidays_dk(d.year)


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


def price_area(lat: float, lon: float) -> str:
    """DK1 west of the Great Belt, DK2 east of it."""
    return "DK2" if lon >= 11.0 else "DK1"


def consumer_price(spot_dkk_mwh: float, hour: int, s: dict[str, Any]) -> float:
    """What a kWh costs at home: spot + tariffs + tax + markup, with VAT."""
    tariff = {**DEFAULT_TARIFF, **(s.get("tariff") or {})}
    net = tariff[TARIFF_HOURS[hour]]
    extra = float(s.get("system_tariff", 0.072)) + float(s.get("elafgift", 0.008)) + float(s.get("markup", 0.012))
    return round((spot_dkk_mwh / 1000 + net + extra) * (1 + float(s.get("vat", 0.25))), 4)


async def fetch_prices(session: Any, area: str, tz: ZoneInfo, s: dict[str, Any]) -> list[dict[str, Any]]:
    """[{start, end, price}] for today and tomorrow (as far as known), like Strømligning's "prices"."""
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
        out.append({"start": t.isoformat(), "end": (t + timedelta(minutes=15)).isoformat(), "price": consumer_price(spot, t.hour, s)})
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

"""Two ways of forecasting, blended by how well each one has really hit - simple first, ML as it earns it.

For each thing forecast (house use, sun, tomorrow's prices before they're out) there is a simple way that works from
day one, and an ML model trained every night on the home's own data. Every night both are checked against what
really happened, and the ML model's share moves towards what it has earned:

- it gets nothing until it has enough data (house and sun: three weeks)
- the share follows the two errors (equal errors: half each), and moves a third of the way per night
- if it starts to miss (a new heat pump, a new car), its share goes down again by itself

Learned values (the car's habits, the battery's real efficiency) are blended with the setting or the datasheet in
the same spirit: the more they have seen, the more they count. What the user sets themselves always wins.
"""

from __future__ import annotations

import time

from datetime import datetime, timedelta
import json
import logging
import math
from pathlib import Path
from statistics import median
from typing import Any

from .sources import is_day_off

_LOGGER = logging.getLogger(__name__)
MIN_DAYS = {"house": 21, "sun": 21, "price": 14}
STEP = 1 / 3


class Mixer:
    """The ML share per kind, from the errors measured night by night."""

    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state.setdefault("blend", {})

    def share(self, kind: str) -> float:
        return float((self.state.get(kind) or {}).get("w", 0.0))

    def info(self, kind: str) -> dict[str, Any]:
        return dict(self.state.get(kind) or {"w": 0.0})

    def update(self, kind: str, err_simple: float | None, err_ml: float | None, ml_days: int) -> None:
        s = self.state.setdefault(kind, {"w": 0.0, "simple": None, "ml": None, "days": 0})
        smooth = lambda old, new: new if old is None else round(0.8 * old + 0.2 * new, 4)  # noqa: E731
        if err_simple is not None:
            s["simple"] = smooth(s.get("simple"), err_simple)
        if err_ml is not None:
            s["ml"] = smooth(s.get("ml"), err_ml)
            s["days"] = int(s.get("days", 0)) + 1
        s["ml_days"] = ml_days
        if ml_days < MIN_DAYS[kind] or s.get("ml") is None or s.get("simple") is None:
            target = 0.0
        else:
            a, b = max(1e-6, s["simple"]) ** 2, max(1e-6, s["ml"]) ** 2
            target = a / (a + b)  # equal errors: half each; the better one gets more
        s["w"] = round(s["w"] + STEP * (target - s["w"]), 3)

    @staticmethod
    def mix(simple: float | None, ml: float | None, w: float) -> float | None:
        if ml is None or w <= 0:
            return simple
        if simple is None:
            return ml
        return round((1 - w) * simple + w * ml, 3)


def mae(pairs: list[tuple[float, float]]) -> float | None:
    return round(sum(abs(a - b) for a, b in pairs) / len(pairs), 4) if pairs else None


# ---------- the sun ----------

class SolarModel:
    """kWh per hour from sunlight, cloud, temperature, hour and time of year - this home's panels, shade and all."""

    def __init__(self) -> None:
        self.model: Any = None
        self.days = 0
        self.top = 0.0

    @staticmethod
    def features(when: datetime, w: dict[str, float]) -> list[float]:
        doy = when.timetuple().tm_yday / 365.25 * 2 * math.pi
        return [when.hour, math.sin(doy), math.cos(doy), float(w.get("sun") or 0), float(w.get("cloud") or 0), float(w.get("temp") or 10)]

    def train(self, pv: dict[datetime, float], weather: Any) -> bool:
        X, y, days = [], [], set()
        for when, kw in pv.items():
            w = weather.at(when)
            if not w or w.get("sun") is None or kw is None or kw < 0:
                continue
            if (w.get("sun") or 0) < 5 and kw < 0.05:
                continue  # night
            X.append(self.features(when, w))
            y.append(kw)
            days.add(when.date())
        if len(days) < 7:
            return False
        from sklearn.ensemble import HistGradientBoostingRegressor

        model = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.06, max_depth=4, min_samples_leaf=8)
        model.fit(X, y)
        self.model, self.days, self.top = model, len(days), max(y)
        return True

    def predict(self, hours: list[datetime], weather: Any) -> dict[datetime, float]:
        if self.model is None:
            return {}
        rows = [(h, weather.at(h)) for h in hours]
        rows = [(h, w) for h, w in rows if w and w.get("sun") is not None]
        if not rows:
            return {}
        out = self.model.predict([self.features(h, w) for h, w in rows])
        return {h: (0.0 if (w.get("sun") or 0) < 3 else round(min(self.top * 1.1, max(0.0, float(v))), 3)) for (h, w), v in zip(rows, out)}


# ---------- tomorrow's prices, before they're out ----------

class PriceModel:
    """Tomorrow's prices before they're published (around 13:00): estimated, and replaced when the real ones come.

    Simple: the shape of the last two weeks (per hour, weekday or day off) at the level of the last day.
    ML: hour, weekday, day off, wind, sun and temperature, yesterday's price for the hour and the last day's level.
    """

    def __init__(self, data_dir: Path) -> None:
        self.file = data_dir / "energy_pilot_prices.json"
        self.hist: dict[str, float] = {}
        self.made: dict[str, dict[str, float]] = {}  # forecasts made before the real prices: {hour: {simple, ml}}
        try:
            d = json.loads(self.file.read_text())
            self.hist, self.made = d.get("hist", {}), d.get("made", {})
        except (OSError, ValueError):
            pass
        self.model: Any = None

    def save(self) -> None:
        try:
            self.file.write_text(json.dumps({"hist": self.hist, "made": self.made}))
        except OSError:
            pass

    @staticmethod
    def key(when: datetime) -> str:
        return when.strftime("%Y-%m-%dT%H")

    def remember(self, prices: dict[datetime, float], now: datetime) -> None:
        """Real prices, kept 120 days."""
        changed = False
        for when, p in prices.items():
            if when.minute == 0 or self.key(when) not in self.hist:
                k = self.key(when)
                if self.hist.get(k) != round(p, 4):
                    self.hist[k], changed = round(p, 4), True
        if changed:
            cut = self.key(now - timedelta(days=120))
            self.hist = {k: v for k, v in self.hist.items() if k >= cut}
            self.save()

    def _level(self, before: datetime) -> float | None:
        day = [v for k, v in self.hist.items() if self.key(before - timedelta(hours=24)) <= k < self.key(before)]
        return sum(day) / len(day) if len(day) >= 12 else None

    def simple(self, when: datetime) -> float | None:
        level = self._level(when.replace(hour=0))
        if level is None:
            return None
        off = is_day_off(when.date())
        same, all_ = [], []
        for k, v in self.hist.items():
            t = datetime.fromisoformat(k + ":00")
            if (when.replace(tzinfo=None) - t).days > 14:
                continue
            all_.append(v)
            if t.hour == when.hour and is_day_off(t.date()) == off:
                same.append(v)
        if not same or not all_:
            return None
        return round(level * (sum(same) / len(same)) / max(1e-6, sum(all_) / len(all_)), 4)

    def _features(self, when: datetime, w: dict[str, float] | None) -> list[float] | None:
        y = self.hist.get(self.key(when - timedelta(days=1)))
        level = self._level(when.replace(hour=0))
        if y is None or level is None:
            return None
        w = w or {}
        return [when.hour, when.weekday(), float(is_day_off(when.date())), float(w.get("wind") or 0), float(w.get("sun") or 0),
                float(w.get("temp") or 10), y, level]

    def train(self, weather: Any, tz: Any) -> int:
        X, y, days = [], [], set()
        for k, v in self.hist.items():
            when = datetime.fromisoformat(k + ":00").replace(tzinfo=tz)
            f = self._features(when, weather.at(when) if weather else None)
            if f is not None:
                X.append(f)
                y.append(v)
                days.add(when.date())
        if len(days) < 7:
            return len(days)
        from sklearn.ensemble import HistGradientBoostingRegressor

        self.model = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.06, max_depth=4, min_samples_leaf=6).fit(X, y)
        return len(days)

    def ml(self, when: datetime, weather: Any) -> float | None:
        if self.model is None:
            return None
        f = self._features(when, weather.at(when) if weather else None)
        # Tomorrow: "yesterday" for tomorrow's hours is today - known.
        return round(float(self.model.predict([f])[0]), 4) if f else None

    def estimate(self, hours: list[datetime], weather: Any, share: float) -> dict[datetime, float]:
        out = {}
        for h in hours:
            s, m = self.simple(h), self.ml(h, weather)
            v = Mixer.mix(s, m, share)
            if v is not None:
                out[h] = v
                k = self.key(h)
                if k not in self.hist and k not in self.made:
                    self.made[k] = {"simple": s, "ml": m}
        return out

    def score(self, now: datetime) -> tuple[float | None, float | None]:
        """The forecasts made earlier, against the real prices that came since."""
        ps, pm = [], []
        for k in [k for k in self.made if k in self.hist]:
            f, real = self.made.pop(k), self.hist[k]
            if f.get("simple") is not None:
                ps.append((f["simple"], real))
            if f.get("ml") is not None:
                pm.append((f["ml"], real))
        cut = self.key(now - timedelta(days=3))
        self.made = {k: v for k, v in self.made.items() if k >= cut}
        self.save()
        return mae(ps), mae(pm)


# ---------- the car's habits ----------

class Habits:
    """When the car leaves (per weekday) and how much it takes - learned from plugging in and out."""

    def __init__(self, state: dict[str, Any]) -> None:
        self.s = state.setdefault("habits", {"leave": {}, "need": [], "plug": None, "session": 0.0})

    def see(self, now: datetime, plugged: bool | None, session_kwh: float | None) -> None:
        if plugged is None:
            return
        was = self.s.get("plug")
        if session_kwh is not None:
            self.s["session"] = max(float(self.s.get("session") or 0), session_kwh)
        if was and not plugged:  # left
            lv = self.s["leave"].setdefault(str(now.weekday()), [])
            lv.append(now.hour * 60 + now.minute)
            self.s["leave"][str(now.weekday())] = lv[-8:]
            if self.s.get("session"):
                self.s["need"] = (self.s.get("need") or [])[-19:] + [round(self.s["session"], 1)]
            self.s["session"] = 0.0
        self.s["plug"] = bool(plugged)

    def leave(self, weekday: int) -> tuple[int, int] | None:
        """Usual leaving time (h, m) for the weekday, once it has seen it 4 times."""
        lv = self.s["leave"].get(str(weekday)) or []
        if len(lv) < 4:
            return None
        m = int(median(lv))
        return m // 60, m % 60

    def need(self, setting: float) -> float:
        n = self.s.get("need") or []
        if not n:
            return setting
        w = min(1.0, len(n) / 10)
        return round((1 - w) * setting + w * median(n), 1)

    def info(self) -> dict[str, Any]:
        return {"leave": {d: self.leave(int(d)) for d in self.s["leave"]}, "need_seen": len(self.s.get("need") or [])}


# ---------- the battery's real efficiency ----------

TAPER_BANDS = (98, 95, 90, 85)  # levels where charging is watched on its own (highest first)


class BatteryLearner:
    """The battery's real usable capacity and efficiency - from what goes in and out against what the level shows.

    Each run of charging (or discharging) of at least 10 points is written down as kWh per percent point:
    charging takes capacity/100 / charge-efficiency per point, discharging gives capacity/100 x discharge-efficiency.
    So their ratio is the round trip, and their geometric mean the capacity - neither needs the other to be known.
    Many write the label's kWh (13), while the level only spans what is usable (~11.5); and batteries wear.
    """

    def __init__(self, state: dict[str, Any]) -> None:
        self.s = state.setdefault("battery_learned", {})
        self.s.setdefault("in_pp", [])
        self.s.setdefault("out_pp", [])
        self.s.setdefault("seg", None)

    def see(self, batt_w: float | None, soc: float | None, hours: float, capacity: float | None = None) -> None:
        if batt_w is None or soc is None:
            return
        seg = self.s.get("seg")
        way = "in" if batt_w > 50 else "out" if batt_w < -50 else None
        if seg and way != seg["way"]:
            moved = abs(soc - seg["soc"])
            if moved >= 10 and seg["kwh"] > 0.5:
                per = seg["kwh"] / moved  # kWh per percent point
                if 0.02 <= per <= 1.0:  # 2 - 100 kWh batteries
                    key = seg["way"] + "_pp"
                    self.s[key] = (self.s.get(key) or [])[-19:] + [round(per, 4)]
            seg = None
        if way and seg is None:
            seg = {"way": way, "soc": soc, "kwh": 0.0}
        if seg:
            seg["kwh"] += abs(batt_w) / 1000 * hours
        self.s["seg"] = seg
        if soc >= 99:
            self.s["last_full"] = time.time()  # full: the cells have been balanced
        if batt_w > 300:  # charging: how hard it charges at which level (most batteries slow down when nearly full)
            band = next((b for b in TAPER_BANDS if soc >= b), 0)
            key = str(band)
            self.s.setdefault("charge_w", {})
            self.s["charge_w"][key] = (self.s["charge_w"].get(key) or [])[-59:] + [round(batt_w)]

    def days_since_full(self) -> float:
        """Days since the battery was last full - 0 until it has been watched for a while (no full charge at once)."""
        if "last_full" not in self.s:
            self.s["last_full"] = time.time()
        return (time.time() - float(self.s["last_full"])) / 86400

    def taper(self) -> tuple[tuple[float, float], ...]:
        """How much of its charge power the battery really takes near full, as (from level, share) - learned by
        comparing the hardest charging seen high up with the hardest seen below 85 %. Nothing until it has seen enough."""
        cw = self.s.get("charge_w") or {}
        low = sorted(cw.get("0") or [])
        if len(low) < 20:
            return ()
        ref = low[int(len(low) * 0.9)]
        out = []
        for band in sorted(TAPER_BANDS):
            vals = sorted(cw.get(str(band)) or [])
            if len(vals) >= 10:
                share = max(0.2, min(1.0, vals[int(len(vals) * 0.9)] / ref))
                if share < 0.95:
                    out.append((float(band), round(share, 2)))
        return tuple(out)

    def _medians(self) -> tuple[float, float, int] | None:
        a, b = self.s.get("in_pp") or [], self.s.get("out_pp") or []
        if len(a) < 3 or len(b) < 3:
            return None
        return median(a), median(b), min(len(a), len(b))

    def capacity(self) -> float | None:
        """Usable kWh, once it has seen at least three runs each way."""
        m = self._medians()
        if not m:
            return None
        cap = (m[0] * m[1]) ** 0.5 * 100
        return round(cap, 1) if 2 <= cap <= 100 else None

    def efficiency(self, datasheet: float) -> float:
        m = self._medians()
        if not m:
            return datasheet
        learned = min(1.0, max(0.7, m[1] / m[0]))
        w = min(1.0, m[2] / 10)
        return round((1 - w) * datasheet + w * learned, 3)

    def info(self, datasheet: float) -> dict[str, Any]:
        m = self._medians()
        return {"efficiency": self.efficiency(datasheet), "capacity": self.capacity(), "seen": m[2] if m else 0}

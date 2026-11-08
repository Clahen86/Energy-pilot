"""Simple first, ML as it earns it - and learned habits and efficiency."""

from datetime import datetime, timedelta
import math
from zoneinfo import ZoneInfo

import pytest

from energy_pilot.blend import BatteryLearner, Habits, Mixer, PriceModel, SolarModel

TZ = ZoneInfo("Europe/Copenhagen")


def test_ml_share_is_earned_and_lost():
    m = Mixer({})
    m.update("house", 0.3, 0.1, ml_days=5)
    assert m.share("house") == 0  # too little data
    for _ in range(10):
        m.update("house", 0.3, 0.1, ml_days=30)
    assert m.share("house") > 0.8  # better: takes over
    for _ in range(15):
        m.update("house", 0.2, 0.6, ml_days=30)
    assert m.share("house") < 0.3  # starts to miss: gives back
    assert Mixer.mix(1.0, 2.0, 0.25) == 1.25 and Mixer.mix(1.0, None, 0.9) == 1.0


class W:
    def __init__(self, hours):
        self.hours = hours

    def at(self, when):
        return self.hours.get(when.replace(minute=0, second=0, microsecond=0))


def test_solar_model_learns_the_panels():
    pytest.importorskip("sklearn")
    start = datetime(2026, 9, 1, tzinfo=TZ)
    weather, pv = {}, {}
    for i in range(24 * 30):
        t = start + timedelta(hours=i)
        sun = max(0.0, math.sin((t.hour - 6) / 12 * math.pi)) * 600 * (0.4 if t.day % 3 == 0 else 1)
        weather[t] = {"sun": sun, "cloud": 80 if t.day % 3 == 0 else 10, "temp": 12}
        pv[t] = sun / 1000 * 5  # a 5 kWp-ish system
    s = SolarModel()
    assert s.train(pv, W(weather))
    t = start + timedelta(days=10, hours=12)
    got = s.predict([t], W(weather))[t]
    assert abs(got - pv[t]) < 0.4


def test_price_estimate_and_score(tmp_path):
    p = PriceModel(tmp_path)
    now = datetime(2026, 11, 7, 10, tzinfo=TZ)
    real = {now.replace(hour=0) - timedelta(days=d) + timedelta(hours=h): 1.0 + (1.0 if 17 <= h < 21 else 0)
            for d in range(0, 10) for h in range(24)}
    p.remember(real, now)
    tomorrow = now.replace(hour=18) + timedelta(days=1)
    est = p.estimate([tomorrow, tomorrow.replace(hour=3)], None, 0.0)
    assert est[tomorrow] > est[tomorrow.replace(hour=3)]  # the evening peak is kept
    p.remember({tomorrow: 2.1}, now)
    es, em = p.score(now)
    assert es is not None and es < 0.5


def test_car_habits_and_need():
    h = Habits({})
    mon = datetime(2026, 11, 2, 7, 30, tzinfo=TZ)
    for wk in range(4):
        t = mon + timedelta(weeks=wk)
        h.see(t - timedelta(hours=10), True, 12.0)
        h.see(t, False, None)
    assert h.leave(0) == (7, 30)
    assert h.leave(1) is None
    assert 12 < h.need(20) < 20  # four charges of 12 kWh pull the setting down


def test_battery_capacity_and_efficiency_learned():
    """A 13 kWh label, 11.5 kWh usable, 95 % each way: both are found from kWh per percent point."""
    b = BatteryLearner({})
    cap, eta = 11.5, 0.95
    for _ in range(6):
        soc = 20.0
        for _ in range(60):  # charge 60 points in an hour
            b.see(cap * 0.60 / eta * 1000, soc, 1 / 60)
            soc += 1.0
        for _ in range(60):  # discharge them again
            b.see(-cap * 0.60 * eta * 1000, soc, 1 / 60)
            soc -= 1.0
    b.see(0, soc, 1 / 60)
    assert abs(b.capacity() - 11.5) < 0.3
    assert abs(b.efficiency(0.92) - 0.92) < 0.02  # learned 0.9025, blended in as it gains weight
    assert BatteryLearner({}).capacity() is None  # nothing seen: not used

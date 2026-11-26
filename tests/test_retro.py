"""What Energy Pilot would have saved last month, from the house's own history."""

from datetime import datetime, timedelta

from energy_pilot.engine import Battery
from energy_pilot.retro import build, estimate, selfuse


def _days(n, night=1.0, evening=4.0, sun_kw=0.0):
    house, sun, prices = [], {}, {}
    t0 = datetime(2026, 11, 1)
    for d in range(n):
        for h in range(24):
            t = t0 + timedelta(days=d, hours=h)
            house.append((t, 1.0))
            sun[t] = sun_kw if 10 <= h < 14 else 0.0
            prices[t] = night if h < 6 else evening if 17 <= h < 21 else 2.0
    return house, sun, prices


def test_a_plan_beats_the_battery_on_its_own_with_cheap_nights():
    b = Battery(capacity_kwh=10, max_charge_kw=3, max_discharge_kw=3, min_soc=10, efficiency=0.9, grid_charge=True)
    res = estimate(build(*_days(10), sell=0.1), b)
    assert res and res["days"] == 10 and res["per_month"] > 0


def test_too_little_history_says_nothing():
    b = Battery(capacity_kwh=10, max_charge_kw=3, max_discharge_kw=3, min_soc=10, efficiency=0.9, grid_charge=True)
    assert estimate(build(*_days(3), sell=0.1), b) is None


def test_the_battery_on_its_own_takes_the_sun_and_gives_it_back():
    b = Battery(capacity_kwh=10, max_charge_kw=3, max_discharge_kw=3, min_soc=10, efficiency=1.0, grid_charge=False)
    days = build(*_days(1, sun_kw=3.0), sell=0.0)
    cost, left = selfuse(next(iter(days.values())), b)
    no_battery = sum(max(0.0, h.house - h.sun) * h.price for h in next(iter(days.values())))
    assert cost < no_battery and left >= 0

"""The engine: the battery fills when power is cheap or the sun gives too much, and is used when it is dear."""

from datetime import datetime, timedelta

from energy_pilot.engine import Battery, Hour, house_forecast, house_profile, plan_battery, plan_car

T0 = datetime(2026, 11, 7, 0, 0)


def day(prices, sun=None, house=0.8, sell=0.0):
    return [Hour(T0 + timedelta(hours=i), p, sell, house, (sun or [0] * 24)[i]) for i, p in enumerate(prices)]


def test_cheap_night_dear_evening():
    prices = [1.0] * 6 + [2.0] * 11 + [4.0] * 4 + [2.0] * 3  # night cheap, 17-21 dear
    p = plan_battery(day(prices), soc_now=10, b=Battery(capacity_kwh=10))
    actions = [s.action for s in p.steps]
    assert "charge_grid" in actions[:6]
    assert all(a == "discharge" for a in actions[17:21])
    assert p.saving > 0


def test_sun_surplus_is_stored_not_sold_cheaply():
    sun = [0] * 9 + [3, 3, 3, 3, 3] + [0] * 10
    p = plan_battery(day([2.0] * 17 + [3.5] * 7, sun=sun, sell=0.3), soc_now=20, b=Battery(capacity_kwh=10, grid_charge=False))
    assert any(s.action == "charge_sun" for s in p.steps[9:14])
    assert not any(s.action == "charge_grid" for s in p.steps)


def test_flat_price_does_nothing_silly():
    p = plan_battery(day([2.0] * 24), soc_now=50, b=Battery())
    assert not any(s.action == "charge_grid" for s in p.steps)  # charging costs losses, never pays


def test_house_profile_and_car():
    rows = [(T0 - timedelta(days=d, hours=-h), 1.5 if h == 18 else 0.5) for d in range(1, 15) for h in range(24)]
    prof = house_profile(rows, T0)
    fc = house_forecast(prof, [T0 + timedelta(hours=18), T0 + timedelta(hours=3)])
    assert fc[0] > 1.2 and fc[1] < 0.7
    hours = day([3, 3, 1, 1, 2, 2] + [3] * 18)
    chosen = plan_car(hours, need_kwh=14, charger_kw=7, ready=T0 + timedelta(hours=7), now=T0)
    assert [h.hour for h in chosen] == [2, 3]

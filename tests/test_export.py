"""Selling from the battery: only when turned on, only with a clear gain after losses and wear, within the limit."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from energy_pilot.engine import Battery, Hour, plan_battery

T0 = datetime(2026, 11, 8, 16, tzinfo=ZoneInfo("Europe/London"))


def hours(sell_peak):
    # buy 0.25, house 0.5 kWh/h; one hour with a high export price
    return [Hour(T0 + timedelta(hours=i), 0.25, sell_peak if i == 2 else 0.05, 0.5, 0.0) for i in range(12)]


def test_off_by_default_never_exports():
    p = plan_battery(hours(0.9), 90, Battery(capacity_kwh=10), end_value=0.2)
    assert all(s.action != "export" for s in p.steps)
    assert all(s.grid_kwh >= -1e-9 for s in p.steps)


def test_sells_at_a_great_export_price():
    b = Battery(capacity_kwh=10, export=True, wear=0.06)
    p = plan_battery(hours(0.9), 90, b, end_value=0.2)
    assert p.steps[2].action == "export" and p.steps[2].grid_kwh < -1


def test_not_for_a_small_gain_after_wear():
    b = Battery(capacity_kwh=10, export=True, wear=0.06)
    p = plan_battery(hours(0.27), 90, b, end_value=0.25)
    assert all(s.action != "export" for s in p.steps)


def test_export_limit():
    b = Battery(capacity_kwh=10, export=True, wear=0.06, export_limit_kw=1.0)
    p = plan_battery(hours(0.9), 90, b, end_value=0.2)
    assert min(s.grid_kwh for s in p.steps) >= -1.0 - 1e-9


def test_built_in_profiles_can_sell():
    # the plan only sells when the profile's export step reaches it (0.39.3: it never did)
    from types import SimpleNamespace

    from energy_pilot.control import Controller

    c = Controller.__new__(Controller)
    c.ov = SimpleNamespace(settings={"inverter_profile": "victron"})
    c.profile_key = lambda *a: "victron"
    assert "export" in c.profile_steps()


def iog_night():
    # Intelligent Go + Agile Outgoing: buy 3.8p at night and 26.7p by day; export pays 17p at night, 25p at the peak
    t = datetime(2026, 11, 12, 23, tzinfo=ZoneInfo("Europe/London"))
    out = []
    for i in range(24):
        start = t + timedelta(hours=i)
        night = start.hour < 6
        out.append(Hour(start, 0.038 if night else 0.267, 0.25 if start.hour in (16, 17, 18) else 0.17, 0.8, 0.0))
    return out


def test_cheap_slots_are_the_night_of_a_night_tariff():
    from energy_pilot.engine import cheap_slots

    h = iog_night()
    assert cheap_slots(h) == frozenset(x.start for x in h if x.price < 0.1)
    assert cheap_slots([Hour(T0, 0.25, 0.0, 0.5, 0.0), Hour(T0 + timedelta(hours=1), 0.25, 0.0, 0.5, 0.0)]) == frozenset()


def test_no_selling_in_the_cheap_hours_when_asked():
    from dataclasses import replace

    from energy_pilot.engine import cheap_slots

    h = iog_night()
    b = Battery(capacity_kwh=32, max_charge_kw=8, max_discharge_kw=5.2, export=True, wear=0.015, efficiency=0.8)
    free = plan_battery(h, 60, b, end_value=0.1)
    cheap = cheap_slots(h)
    assert any(s.action == "export" and s.start in cheap for s in free.steps)  # arbitrage at night when allowed
    kept = plan_battery(h, 60, replace(b, no_export=cheap), end_value=0.1)
    assert not any(s.action == "export" and s.start in cheap for s in kept.steps)
    assert any(s.action == "charge_grid" for s in kept.steps)  # it still charges on the cheap power
    assert any(s.action == "export" and s.start.hour in (16, 17, 18) for s in kept.steps)  # and sells at the peak

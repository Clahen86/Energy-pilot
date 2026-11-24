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


def test_never_sells_below_what_buying_it_back_costs():
    # The report: sell 1.29 at 23 while the night costs 1.22 to buy back - with loss and wear in and out, a loss.
    t0 = datetime(2026, 11, 18, 20, tzinfo=ZoneInfo("Europe/Copenhagen"))
    buy = [2.4, 2.3, 2.2, 1.29, 1.25, 1.22, 1.24, 2.2, 2.5, 2.6]
    sell = [1.50, 1.44, 1.39, 1.29, 0.70, 0.68, 0.70, 1.2, 1.3, 1.3]
    hrs = [Hour(t0 + timedelta(hours=i), buy[i], sell[i], 1.4, 0.0) for i in range(len(buy))]
    b = Battery(capacity_kwh=76.6, export=True, wear=0.15, efficiency=0.95, min_soc=15)
    p = plan_battery(hrs, 30, b, end_value=1.5)
    assert all(s.action != "export" and s.grid_kwh >= -1e-9 for s in p.steps)  # not even a rest from rounding


def test_learned_efficiency_never_above_95_percent():
    from energy_pilot.blend import BatteryLearner

    bl = BatteryLearner({"battery_learned": {"in_pp": [0.77] * 10, "out_pp": [0.765] * 10}})
    assert bl.efficiency(0.92) == 0.95  # 0.99 from the battery's own meter misses the inverter's loss


def test_selling_not_blocked_before_the_controls_are_looked_up():
    """Just started: the plan is made before the inverter's controls are found - not taken as missing, so the first
    plan still sells and no "selling is blocked" shows. Once looked up, missing controls do block it."""
    from types import SimpleNamespace

    from energy_pilot.engine import Engine

    ctl = SimpleNamespace(discovered=False, profile_steps=lambda: {"export": [{}]}, check=lambda: {"export": {"missing": ["x"]}})
    e = Engine.__new__(Engine)
    e.ov = SimpleNamespace(settings={"battery_export": True}, controller=ctl)
    assert e.can_export()
    ctl.discovered = True
    assert not e.can_export()

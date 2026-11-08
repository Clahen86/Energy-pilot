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

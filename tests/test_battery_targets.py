from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from energy_pilot.engine import Battery, Hour, battery_targets, plan_battery, target_levels

TZ = ZoneInfo("Europe/Copenhagen")
T0 = datetime(2026, 11, 11, 22, 0, tzinfo=TZ)


def night(n=12):
    # flat prices: nothing pays, so without a target the battery isn't charged
    return [Hour(T0 + timedelta(hours=i), price=2.0, sell=0.0, house=0.5, sun=0.0) for i in range(n)]


def soc_at(plan, t):
    for s in plan.steps:
        if s.start + timedelta(hours=1) == t:
            return s.soc_end


def test_settings_rows():
    s = {"battery_targets": [{"time": "07:00", "soc": 80}, {"time": "x", "soc": 5}, {"time": "25:00", "soc": 50}]}
    assert battery_targets(s) == ((7, 0, 80.0),)


def test_boundary_found():
    assert target_levels(night(), ((7, 0, 80.0),)) == {9: 80.0}
    assert target_levels(night(), ()) == {}


def test_target_is_reached_even_when_it_does_not_pay():
    b = Battery(capacity_kwh=10, max_charge_kw=3, min_soc=10, efficiency=0.9, grid_max_soc=95)
    free = plan_battery(night(), 20, b, end_value=0.0)
    assert soc_at(free, T0 + timedelta(hours=9)) < 80
    b.targets, b.grid_max_soc = ((7, 0, 80.0),), 95
    p = plan_battery(night(), 20, b, end_value=0.0)
    assert soc_at(p, T0 + timedelta(hours=9)) >= 80


def test_unreachable_target_gets_as_close_as_it_can():
    b = Battery(capacity_kwh=10, max_charge_kw=1, min_soc=10, efficiency=1.0, targets=((0, 0, 100.0),))
    p = plan_battery(night(), 20, b, end_value=0.0)
    assert soc_at(p, T0 + timedelta(hours=2)) >= 36  # two hours at 1 kW: +20 %, less what the house took

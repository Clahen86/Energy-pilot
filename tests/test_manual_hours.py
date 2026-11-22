"""The user's own hours: charge, sell or keep - the plan plans the rest around them."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from energy_pilot.engine import Battery, Hour, plan_battery

T0 = datetime(2026, 11, 22, 12, tzinfo=ZoneInfo("Europe/Copenhagen"))


def _hours():
    return [Hour(T0 + timedelta(hours=i), 2.0, 0.5, 1.0, 0.0) for i in range(8)]


def _key(i):
    return (T0 + timedelta(hours=i)).strftime("%Y-%m-%dT%H")


def test_charge_here_fills_it_in_that_hour():
    b = Battery(capacity_kwh=13, max_charge_kw=6, max_discharge_kw=6, min_soc=10, force={_key(2): "charge"})
    p = plan_battery(_hours(), 30, b, end_value=1.0)
    assert p.steps[2].action == "charge_grid" and p.steps[2].soc_end - p.steps[2].soc_start >= 40


def test_keep_the_power_holds_and_sell_here_sells_even_when_selling_is_off():
    b = Battery(capacity_kwh=13, max_charge_kw=6, max_discharge_kw=6, min_soc=10, force={_key(0): "hold", _key(3): "sell"})
    p = plan_battery(_hours(), 80, b, end_value=1.0)
    assert p.steps[0].soc_end == p.steps[0].soc_start
    assert p.steps[3].action == "export"


def test_no_choice_plans_as_always():
    b = Battery(capacity_kwh=13, max_charge_kw=6, max_discharge_kw=6, min_soc=10)
    assert all(s.action != "export" for s in plan_battery(_hours(), 80, b, end_value=1.0).steps)

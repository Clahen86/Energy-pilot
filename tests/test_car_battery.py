"""The car in the battery plan: the battery only helps it with what the house won't need before it fills again."""

from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from energy_pilot.engine import Battery, Hour, car_load, plan_battery

T0 = datetime(2026, 7, 1, 12, tzinfo=ZoneInfo("Europe/Copenhagen"))
B = Battery(capacity_kwh=13, max_charge_kw=6, max_discharge_kw=6, min_soc=10, grid_charge=True, wear=0.05)


def _with_car(hours, load):
    return [replace(h, house=h.house + load.get(h.start, 0.0)) for h in hours]


def test_car_load_charging_by_itself_runs_until_it_has_what_it_lacks():
    hours = [Hour(T0 + timedelta(hours=i), 1.0, 0.0, 0.5, 0.0) for i in range(24)]
    load = car_load(hours, set(), 7.4, 7400, 10.0, T0)
    assert [round(v, 1) for v in load.values()] == [7.4, 2.6]
    assert car_load(hours, set(), 7.4, 0, 10.0, T0) == {}  # not charging, nothing planned: no car in the plan
    planned = {hours[3].start, hours[4].start}
    assert car_load(hours, planned, 7.4, 0, 10.0, T0) == {hours[3].start: 7.4, hours[4].start: 7.4}


def test_dear_evening_ahead_the_battery_holds_and_the_car_takes_the_grid():
    # 12-15 the car charges at 2 kr, 15-21 the house pays 3.5 kr, no sun to refill it: the battery is kept for the house
    hours = [Hour(T0 + timedelta(hours=i), 2.0 if i < 3 else 3.5, 0.0, 1.0, 0.0) for i in range(9)]
    hours = _with_car(hours, car_load(hours, set(), 7.4, 7400, 20.0, T0))
    p = plan_battery(hours, 60, B, end_value=2.5)
    assert all(s.action != "discharge" for s in p.steps[:3])
    assert any(s.action == "discharge" for s in p.steps[3:])


def test_sunny_day_the_battery_helps_the_car_and_is_full_again_for_the_evening():
    # 12: the car charges at 2 kr; 13-17 the sun gives far more than the house uses (sold for 0.3); 18-23 dear evening
    hours = [Hour(T0, 2.0, 0.3, 0.5, 1.0)]
    hours += [Hour(T0 + timedelta(hours=1 + i), 1.5, 0.3, 0.5, 5.0) for i in range(5)]
    hours += [Hour(T0 + timedelta(hours=6 + i), 3.0, 0.3, 1.0, 0.0) for i in range(6)]
    hours = _with_car(hours, car_load(hours, set(), 7.4, 7400, 5.0, T0))
    p = plan_battery(hours, 90, B, end_value=2.0)
    assert p.steps[0].action == "discharge"  # it would be full and sell anyway: the car gets it
    assert p.steps[5].soc_end >= 95  # the sun fills it again before the evening
    assert min(s.soc_end for s in p.steps) >= B.min_soc


def test_cheap_power_now_the_battery_never_empties_into_the_car():
    hours = [Hour(T0 + timedelta(hours=i), 0.5 if i < 4 else 3.0, 0.0, 0.5, 0.0) for i in range(10)]
    hours = _with_car(hours, car_load(hours, set(), 7.4, 7400, 20.0, T0))
    p = plan_battery(hours, 80, B, end_value=2.5)
    assert all(s.action != "discharge" for s in p.steps[:3])

"""The battery's real charging near full is learned; the battery doesn't empty itself into the car."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from energy_pilot.blend import BatteryLearner
from energy_pilot.engine import Battery, Hour, plan_battery

T0 = datetime(2026, 11, 9, 0, tzinfo=ZoneInfo("Europe/Copenhagen"))


def test_taper_learned_from_what_it_really_takes():
    bl = BatteryLearner({})
    for _ in range(25):
        bl.see(3000, 50, 30 / 3600)  # full speed at half
    for _ in range(12):
        bl.see(1200, 96, 30 / 3600)  # 40 % of it near full
    assert bl.taper() == ((95.0, 0.4),)
    assert BatteryLearner({}).taper() == ()  # nothing seen: no guess


def test_taper_never_lower_than_a_level_above():
    """A user's battery learned 20 % at 85 % but 88 % at 90 %: slow charging that was asked for, not the battery."""
    bl = BatteryLearner({})
    for _ in range(25):
        bl.see(8000, 50, 30 / 3600)
    for _ in range(12):
        bl.see(1600, 86, 30 / 3600)  # the plan's last half hour, charging gently
        bl.see(7040, 91, 30 / 3600)  # full speed higher up
    assert bl.taper() == ((85.0, 0.88), (90.0, 0.88))


def test_plan_respects_the_taper():
    hours = [Hour(T0 + timedelta(hours=i), 0.1 if i < 4 else 2.0, 0.0, 0.5, 0.0) for i in range(12)]
    b = Battery(capacity_kwh=10, max_charge_kw=5, grid_charge=True, taper=((90.0, 0.2),))
    p = plan_battery(hours, 80, b, end_value=1.5)
    # above 90 % it can only take 1 kW an hour (10 % of 10 kWh): so 4 cheap hours can't fill it right after 90
    jumps = [s.soc_end - s.soc_start for s in p.steps[:4] if s.soc_start >= 90]
    assert all(j <= 10.5 for j in jumps)


def test_no_discharge_while_the_car_charges():
    hours = [Hour(T0 + timedelta(hours=i), 2.0, 0.0, 1.0, 0.0) for i in range(6)]
    car = frozenset({hours[2].start, hours[3].start})
    p = plan_battery(hours, 80, Battery(capacity_kwh=10, no_discharge=car), end_value=0.5)
    assert all(s.action != "discharge" for s in p.steps if s.start in car)
    assert any(s.action == "discharge" for s in p.steps if s.start not in car)


def test_grid_charging_stops_at_the_limit_but_the_sun_may_fill_it():
    night = [Hour(T0 + timedelta(hours=i), 0.1, 0.0, 0.3, 0.0) for i in range(6)]
    day = [Hour(T0 + timedelta(hours=6 + i), 3.0, 0.0, 0.3, 0.0) for i in range(6)]
    p = plan_battery(night + day, 50, Battery(capacity_kwh=10, grid_charge=True, grid_max_soc=95), end_value=2.0)
    assert max(s.soc_end for s in p.steps) <= 95
    sunny = [Hour(T0 + timedelta(hours=i), 0.5, 0.0, 0.3, 4.0) for i in range(6)]
    p2 = plan_battery(sunny + day, 80, Battery(capacity_kwh=10, grid_charge=True, grid_max_soc=95), end_value=2.0)
    assert max(s.soc_end for s in p2.steps) == 100

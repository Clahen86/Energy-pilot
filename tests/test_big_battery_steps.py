"""A big battery is planned in 1 % steps: a 2 % step of 45 kWh (0.9 kWh) is more than the house needs in a quiet
hour, and the plan threw the rest of the step away - so it charged too little at night and bought in the dear hours."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from energy_pilot.engine import Battery, Hour, plan_battery

T0 = datetime(2026, 11, 27, 1, tzinfo=ZoneInfo("Europe/Copenhagen"))


def _day():
    night = [Hour(T0 + timedelta(hours=i), 2.45, 1.6, 0.7, 0.0) for i in range(5)]
    dear = [Hour(T0 + timedelta(hours=5 + i), 4.0, 2.6, 0.5, 0.0) for i in range(14)]
    return night + dear


def _battery(kwh):
    return Battery(capacity_kwh=kwh, max_charge_kw=11.85, max_discharge_kw=11.85, min_soc=10, grid_max_soc=95,
                   efficiency=0.904, grid_charge=True, export=True, wear=0.133)


def test_a_big_battery_covers_the_quiet_dear_hours():
    p = plan_battery(_day(), 10, _battery(45), end_value=2.6)
    bought = sum(max(0.0, s.grid_kwh) for s in p.steps[5:])
    assert bought < 0.1 * 14  # 2 % steps bought all 0.5 kWh in every dear hour (7 kWh)
    assert p.cost < plan_battery(_day(), 10, _battery(45), end_value=2.6, step_pct=2.0).cost


def test_a_small_battery_keeps_its_2_percent_steps():
    p = plan_battery(_day(), 10, _battery(10), end_value=2.6)
    assert all(round(s.soc_end) % 2 == 0 for s in p.steps)

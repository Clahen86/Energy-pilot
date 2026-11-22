"""Gentle charging: slots at nearly the same price share the charge at a calm power; a clearly cheaper slot still wins."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from energy_pilot.engine import Battery, Hour, plan_battery

T0 = datetime(2026, 11, 22, 0, tzinfo=ZoneInfo("Europe/Copenhagen"))
B = Battery(capacity_kwh=13, max_charge_kw=6, max_discharge_kw=6, min_soc=10, grid_charge=True)


def _night(prices):
    return [Hour(T0 + timedelta(hours=i), p, 0.0, 0.3, 0.0) for i, p in enumerate(prices)] + \
           [Hour(T0 + timedelta(hours=len(prices) + i), 3.0, 0.0, 1.5, 0.0) for i in range(6)]


def test_nearly_the_same_price_spreads_the_charge():
    p = plan_battery(_night([1.00, 1.00, 1.01, 1.00]), 30, B, end_value=2.0)
    grid_kwh = [s.grid_kwh - 0.3 for s in p.steps[:4]]
    assert max(grid_kwh) < 5.0  # not all at full power in one hour
    assert sum(1 for g in grid_kwh if g > 0.5) >= 3  # shared over the cheap hours


def test_a_clearly_cheaper_hour_still_wins():
    p = plan_battery(_night([2.0, 0.5, 2.0, 2.0]), 30, B, end_value=2.5)
    assert p.steps[1].action == "charge_grid" and p.steps[1].grid_kwh > 5.0

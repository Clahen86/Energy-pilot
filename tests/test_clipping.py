"""Sun over the limit on selling is lost: the plan keeps room for it; the limit is found by itself."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from energy_pilot.checks import ExportCap
from energy_pilot.engine import Battery, Hour, plan_battery

T0 = datetime(2026, 7, 1, 4, tzinfo=ZoneInfo("Europe/Copenhagen"))


def _day():
    # 4-8 cheap (0.2), 8-14 the sun gives 8 kWh/h but only 3 may be sold (0.4), 14-22 dear (3.0)
    return [Hour(T0 + timedelta(hours=i), 0.2, 0.4, 0.5, 0.0) for i in range(4)] + \
           [Hour(T0 + timedelta(hours=4 + i), 1.0, 0.4, 0.5, 8.0) for i in range(6)] + \
           [Hour(T0 + timedelta(hours=10 + i), 3.0, 0.4, 1.0, 0.0) for i in range(8)]


def test_keeps_room_for_the_sun_that_would_be_lost():
    b = Battery(capacity_kwh=13, max_charge_kw=6, max_discharge_kw=6, min_soc=10, grid_charge=True, export_limit_kw=3.0)
    p = plan_battery(_day(), 40, b, end_value=2.5)
    assert all(s.action != "charge_grid" for s in p.steps[:4])  # nothing bought: the sun fills it for free
    assert p.steps[9].soc_end == 100


def test_finds_a_limit_the_export_keeps_stopping_at():
    cap, state = None, {}
    c = ExportCap(state)
    day = datetime(2026, 7, 1, 12, tzinfo=ZoneInfo("Europe/Copenhagen"))
    for d, top in enumerate([3000, 2990, 3010, 1800, 3000, 2500, 2995]):
        for _ in range(4):
            c.see(day + timedelta(days=d), -top)
    cap = c.kw()
    assert cap == 3.01
    free = ExportCap({})
    for d, top in enumerate([3000, 4200, 2500, 5100, 1800, 3900, 4600]):
        for _ in range(4):
            free.see(day + timedelta(days=d), -top)
    assert free.kw() is None  # varies freely: no limit


def test_without_a_limit_it_would_buy_cheap_and_sell_the_sun():
    b = Battery(capacity_kwh=13, max_charge_kw=6, max_discharge_kw=6, min_soc=10, grid_charge=True)
    p = plan_battery(_day(), 40, b, end_value=2.5)
    assert any(s.action == "charge_grid" for s in p.steps[:4])  # the difference the limit makes

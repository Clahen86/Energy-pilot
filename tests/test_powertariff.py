"""Power tariffs: the month's peaks are kept, and the plan shaves them with the battery."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from energy_pilot import powertariff as pt
from energy_pilot.carspeed import decide
from energy_pilot.engine import Battery, Hour, plan_battery

T0 = datetime(2026, 11, 9, 0, tzinfo=ZoneInfo("Europe/Brussels"))


def test_peaks_per_window_and_top_days():
    m = pt.MonthPeak({})
    for day, kw in ((1, 3.0), (2, 5.0), (3, 4.0), (4, 2.0)):
        t = T0.replace(day=day, hour=18)
        for i in range(30):  # 15 minutes of samples every 30 s, then the next window closes it
            m.see(t + timedelta(seconds=30 * i), kw * 1000, 15)
        m.see(t + timedelta(minutes=15), 0, 15)
    assert m.level(1) == 5.0 and m.level(3) == 4.0
    assert m.limit(1) == 5.0
    assert pt.MonthPeak({}).limit(1) == pt.FLOOR_KW  # nothing seen yet: at least 2 kW


def test_battery_shaves_a_new_peak():
    # flat price; the house takes 6 kW at 18:00, the month's peak so far is 3 kW at 10 per kW
    hours = [Hour(T0 + timedelta(hours=i), 0.3, 0.0, 6.0 if i == 18 else 1.0, 0.0) for i in range(24)]
    b = Battery(capacity_kwh=10, max_charge_kw=3, max_discharge_kw=5, peak_kw=3.0, peak_price=10.0)
    p = plan_battery(hours, 60, b, end_value=0.3)
    assert p.steps[18].action == "discharge" and p.steps[18].grid_kwh <= 3.0 + 1e-6


def test_car_turned_down_not_stopped_for_the_peak():
    flow = {"plug": True, "pv": 0, "house": 2000, "battery": 0, "grid": 2000, "ev": 0}
    d = decide(flow, {"charger_kw": 11, "peak_kw": 4.0}, True, False, 10, False)
    assert d["charge"] and d["current"] == 6 and d["why"] == "planned+peak"

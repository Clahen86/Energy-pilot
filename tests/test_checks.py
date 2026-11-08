"""Self-check: settings that spoil the plan are found and explained."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from energy_pilot import checks
from energy_pilot.engine import Battery, Hour, plan_battery

T0 = datetime(2026, 11, 8, 21, tzinfo=ZoneInfo("Europe/London"))


def night(car_kw=7.0):
    # cheap 23-05 with the car charging 00-04, dear all day after
    out = []
    for i in range(24):
        t = T0 + timedelta(hours=i)
        cheap = t.hour >= 23 or t.hour < 5
        house = (0.6 if cheap else 1.5) + (car_kw if 0 <= t.hour < 4 else 0.0)
        out.append(Hour(t, 0.07 if cheap else 0.27, 0.15, house, 0.0))
    return out


def engine(settings, soc=20, learned=None, ev_seen=None, peak=None):
    ov = SimpleNamespace(settings=settings, flow=lambda: {"soc": soc}, role=lambda r: None)
    return SimpleNamespace(ov=ov, batt_learn=SimpleNamespace(capacity=lambda: learned), ev_detected=ev_seen,
                           grid_peak=SimpleNamespace(kw=lambda: peak))


def test_import_limit_that_blocks_cheap_charging():
    b = Battery(capacity_kwh=32, max_charge_kw=8, max_discharge_kw=4, import_limit_kw=8, grid_charge=True)
    h = night()
    p = plan_battery(h, 20, b, end_value=0.07)
    found = checks.run(engine({"import_limit_kw": 8}), h, b, p, 0.07)
    assert [c["key"] for c in found] == ["fuse_blocks"]
    assert found[0]["fix"] == {"import_limit_kw": None}


def test_house_bought_more_than_the_limit():
    b = Battery(capacity_kwh=10, import_limit_kw=5)
    found = checks.run(engine({"import_limit_kw": 5}, peak=9.2), [], b, None, 0.0)
    assert found[0]["key"] == "fuse_low" and found[0]["vals"]["peak"] == 9.2


def test_capacity_and_car_and_nothing_when_fine():
    b = Battery(capacity_kwh=32)
    keys = [c["key"] for c in checks.run(engine({"battery_kwh": 32, "ev_in_house": False}, learned=34.0, ev_seen=True), [], b, None, 0.0)]
    assert keys == ["capacity", "ev_house"]
    assert checks.run(engine({}), [], Battery(), None, 0.0) == []


def test_selling_explained_when_it_never_pays():
    b = Battery(capacity_kwh=10, export=True, wear=0.06)
    h = [Hour(T0 + timedelta(hours=i), 0.27, 0.15, 0.5, 0.0) for i in range(12)]
    p = plan_battery(h, 90, b, end_value=0.25)
    found = checks.run(engine({"battery_export": True, "sell": True}, soc=90), h, b, p, 0.25)
    assert found[0]["key"] == "export_no_gain" and found[0]["vals"] == {"sell": 0.15, "worth": 0.27}


def test_grid_peak_is_a_two_minute_average():
    gp = checks.GridPeak({})
    for w in (12000, 1000, 1000, 1000):  # one spike
        gp.see(T0, w)
    assert gp.kw() == 3.75
    for w in (6000,) * 4:
        gp.see(T0, w)
    assert gp.kw() == 6.0

"""The car's current: the sun's surplus, full speed when planned, never over the fuse."""

from energy_pilot.carspeed import decide

S = {"charger_kw": 11, "charger_phases": 3, "import_limit_kw": 17}


def f(pv=0, house=500, battery=0, plug=True, grid=None, ev=0):
    return {"pv": pv, "house": house, "battery": battery, "plug": plug, "grid": grid, "ev": ev}


def test_follows_the_sun_outside_the_plan():
    d = decide(f(pv=8000, house=600), S, planned=False, manual=False, need_kwh=20, sun_was_on=False)
    assert d["charge"] and d["sun"] and d["current"] == 10  # (8000-600)/690 = 10.7 -> 10 A
    d = decide(f(pv=8100, house=600, battery=3000), S, planned=False, manual=False, need_kwh=20, sun_was_on=False)
    assert d["current"] == 6  # the house battery takes the sun first: 4500 W -> 6 A


def test_margin_stops_flapping():
    small = f(pv=4600, house=500)  # 4100 W: just under 6 A on 3 phases (4140 W)
    assert not decide(small, S, False, False, 20, sun_was_on=False)["charge"]  # won't start
    assert decide(small, S, False, False, 20, sun_was_on=True)["charge"]  # but keeps going


def test_full_speed_in_planned_hours_and_the_fuse():
    d = decide(f(house=500), S, planned=True, manual=False, need_kwh=20, sun_was_on=False)
    assert d["current"] == 16 and d["why"] == "planned"
    d = decide(f(house=9000), S, planned=True, manual=False, need_kwh=20, sun_was_on=False)
    assert d["current"] == 11 and "fuse" in d["why"]  # 17 kW - 9 kW = 8 kW -> 11 A
    assert not decide(f(house=14000), S, True, False, 20, False)["charge"]  # not even 6 A fits


def test_switches_off():
    assert decide(f(pv=8000), {**S, "ev_follow_sun": False}, False, False, 20, False)["charge"] is False
    d = decide(f(house=9000), {**S, "ev_fuse_guard": False}, True, False, 20, False)
    assert d["current"] == 16
    assert not decide(f(plug=False), S, True, False, 20, False)["charge"]

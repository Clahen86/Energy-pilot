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


def test_fixed_steps_stop_when_the_lowest_does_not_fit():
    from energy_pilot.adapters import lowest_amps
    from energy_pilot.carspeed import decide

    sel = "select.all_house_vevor_ev_charger_charging_current"
    states = {sel: {"attributes": {"options": ["8A", "10A", "13A", "16A", "20A", "24A", "32A"]}}}
    assert lowest_amps([sel, "switch.vevor_ev_charger"], states) == 8
    # 6 kW subscription, the house takes 4.4 kW: room for ~6.9 A - the lowest step (8 A) would go over: stop
    flow = {"pv": 0.0, "house": 4400.0, "battery": 0.0, "plug": True, "ev": 0.0, "grid": 4400.0}
    s = {"charger_kw": 7.4, "import_limit_kw": 6, "min_a": 8}
    assert decide(flow, s, True, False, 10.0, False)["charge"] is False
    s["min_a"] = None  # a charger that can go down to 6 A still charges
    assert decide(flow, s, True, False, 10.0, False)["current"] == 6


def test_battery_without_grid_charging_gets_the_sun_first():
    sf = {**S, "batt_sun_w": 3000}
    d = decide(f(pv=8000, house=600), sf, planned=True, manual=False, need_kwh=20, sun_was_on=False)
    assert d["charge"] and d["current"] == 6  # (8000-600-3000)/690 = 6.4 A: the battery keeps 3 kW of sun
    d = decide(f(pv=4000, house=600), sf, planned=True, manual=False, need_kwh=20, sun_was_on=False)
    assert d["charge"] and d["current"] == 6  # turned down to the lowest, never stopped in its planned hours
    assert not decide(f(pv=4000, house=600), sf, planned=False, manual=False, need_kwh=20, sun_was_on=False)["charge"]
    assert decide(f(pv=8000, house=600), sf, planned=False, manual=True, need_kwh=20, sun_was_on=False)["current"] == 16
    on_off = decide(f(pv=8000, house=600), {**sf, "onoff": True}, planned=True, manual=False, need_kwh=20, sun_was_on=False)
    assert on_off["current"] == 16  # a charger that can't be turned down isn't touched
    assert decide(f(house=500), sf, planned=True, manual=False, need_kwh=20, sun_was_on=False)["current"] == 16  # no sun


def test_car_first_gets_the_sun_the_battery_was_taking():
    # The battery soaks up the whole surplus (grid 0): with "Car first" the car starts on it anyway - before, it waited
    # until the battery was full. Without "Car first" the battery keeps it, as before.
    from energy_pilot.carspeed import decide as _decide

    flow = {"plug": True, "pv": 3500.0, "house": 600.0, "battery": 2900.0, "grid": 0.0, "ev": 0.0}
    s = {"charger_kw": 1.6, "onoff": True, "ev_follow_sun": True}
    assert not _decide(flow, s, planned=False, manual=False, need_kwh=10, sun_was_on=False)["charge"]
    d = _decide(flow, {**s, "style": "car_first"}, planned=False, manual=False, need_kwh=10, sun_was_on=False)
    assert d["charge"] and d["why"] == "sun"
    # Not enough sun for the car even with all of it: it waits
    weak = {**flow, "pv": 1500.0, "battery": 900.0}
    assert not _decide(weak, {**s, "style": "car_first"}, planned=False, manual=False, need_kwh=10, sun_was_on=False)["charge"]

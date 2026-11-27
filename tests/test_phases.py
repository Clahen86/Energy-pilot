"""The main fuse per phase (#91): the meter's three phase currents found by themselves; the car and the battery give
way before the busiest phase reaches the fuse."""

from energy_pilot import phases
from energy_pilot.carspeed import decide


def _a(v):
    return {"state": str(v), "attributes": {"unit_of_measurement": "A", "device_class": "current"}}


SLIMME = {"sensor.current_phase_l1": _a(22), "sensor.current_phase_l2": _a(4), "sensor.current_phase_l3": _a(5)}


def test_the_meters_phases_are_found():
    assert phases.find(SLIMME) == ["sensor.current_phase_l1", "sensor.current_phase_l2", "sensor.current_phase_l3"]
    hw = {f"sensor.p1_meter_active_current_phase_{n}": _a(3) for n in (1, 2, 3)}
    assert phases.find(hw) == [f"sensor.p1_meter_active_current_phase_{n}" for n in (1, 2, 3)]


def test_inverter_or_charger_currents_are_not_the_meter():
    deye = {f"sensor.deye_grid_current_l{n}": _a(3) for n in (1, 2, 3)}
    keba = {f"sensor.keba_current_phase_{n}": _a(16) for n in (1, 2, 3)}
    assert phases.find({**deye, **keba}) is None
    assert phases.find({**SLIMME, **deye}) == ["sensor.current_phase_l1", "sensor.current_phase_l2", "sensor.current_phase_l3"]
    two = {**SLIMME, **{f"sensor.p1_meter_active_current_phase_{n}": _a(3) for n in (1, 2, 3)}}
    assert phases.find(two) is None  # two meters: not guessed
    assert phases.find({"sensor.current_phase_l1": _a(3), "sensor.current_phase_l2": _a(3)}) is None


def test_room_on_the_busiest_phase():
    ents = phases.find(SLIMME)
    assert phases.room_a(SLIMME, ents, 25) == 25 - phases.MARGIN_A - 22
    assert phases.room_a(SLIMME, ents, None) is None
    assert phases.room_a({**SLIMME, "sensor.current_phase_l2": {"state": "unavailable"}}, ents, 25) is None


def _car(room, ev_w=0.0):
    flow = {"plug": True, "pv": 0.0, "house": 6000.0, "battery": 0.0, "grid": 6000.0 + ev_w, "ev": ev_w}
    s = {"charger_kw": 11, "charger_phases": 3, "ev_follow_sun": False, "phase_room_a": room}
    return decide(flow, s, planned=True, manual=False, need_kwh=20, sun_was_on=False)


def test_the_car_turns_down_on_the_busiest_phase():
    assert _car(None)["current"] == 16
    d = _car(2.0, ev_w=16 * 690)  # charging at 16 A, the busiest phase 2 A from the fuse: 18 A fits, 16 stays
    assert d["charge"] and d["current"] == 16
    d = _car(-6.0, ev_w=16 * 690)  # 6 A over: down to 10 A
    assert d["charge"] and d["current"] == 10 and d["why"].endswith("+fuse")
    d = _car(-12.0, ev_w=16 * 690)  # even 6 A is too much: stopped
    assert not d["charge"] and d["why"] == "fuse"
    assert not _car(3.0)["charge"]  # not charging yet, only 3 A left: not started


def test_the_battery_spreads_on_three_phases_when_big():
    assert phases.battery_phases(6) == 3 and phases.battery_phases(3) == 1


def test_the_battery_charge_gives_way_on_the_busiest_phase():
    from test_import_limit_live import _ctl

    c = _ctl(1000, limit=None)
    c.ov.flow = lambda: {"soc": 40, "house": 1000, "pv": 0, "ev": 0, "battery": 4000}
    c.ov.phase_room_a = lambda: -2.0  # 2 A over, the battery takes 4000 / 690 = 5.8 A a phase now: 3.8 A fits
    assert c.intents()["battery"]["ctx"]["power_w"] == 2600  # 3.8 A x 690 V = 2.62 kW, in 100 W steps
    c.ov.phase_room_a = lambda: 10.0
    assert c.intents()["battery"]["ctx"]["power_w"] == 5000
    c.ov.phase_room_a = lambda: -6.0
    assert c.intents()["battery"]["intent"] == "hold"

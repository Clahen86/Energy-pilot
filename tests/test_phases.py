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


def test_the_battery_spreads_on_three_phases_only_when_the_inverter_shows_them():
    three = ["sensor.inverter_l1_current", "sensor.inverter_l2_current", "sensor.inverter_l3_current"]
    assert phases.battery_phases(6, three) == 3 and phases.battery_phases(3, three) == 1
    # A big single-phase hybrid (Deye SG01LP1, Growatt SPH): one phase - the careful guess
    assert phases.battery_phases(8, ["sensor.growatt_sph_battery_power", "number.growatt_charge_rate"]) == 1
    assert phases.battery_phases(6) == 1


def test_nan_or_inf_on_a_phase_is_not_read():
    ents = ["sensor.l1", "sensor.l2", "sensor.l3"]
    for bad in ("nan", "inf", "-inf"):
        for i in range(3):
            st = {e: {"state": "5"} for e in ents}
            st[ents[i]] = {"state": bad}
            assert phases.worst(st, ents) is None and phases.room_a(st, ents, 25) is None


def test_the_battery_charge_gives_way_on_the_busiest_phase():
    from test_import_limit_live import _ctl

    c = _ctl(1000, limit=None)
    c.entities = {"battery": ["sensor.inverter_l1_power", "sensor.inverter_l2_power", "sensor.inverter_l3_power"]}
    c.ov.flow = lambda: {"soc": 40, "house": 1000, "pv": 0, "ev": 0, "battery": 4000}
    c.ov.phase_room_a = lambda: -2.0  # 2 A over, the battery takes 4000 / 690 = 5.8 A a phase now: 3.8 A fits
    assert c.intents()["battery"]["ctx"]["power_w"] == 2600  # 3.8 A x 690 V = 2.62 kW, in 100 W steps
    c.ov.phase_room_a = lambda: 10.0
    assert c.intents()["battery"]["ctx"]["power_w"] == 5000
    c.ov.phase_room_a = lambda: -6.0
    assert c.intents()["battery"]["intent"] == "hold"


def test_a_single_phase_battery_is_held_to_one_phase():
    from test_import_limit_live import _ctl

    c = _ctl(1000, limit=None)  # no L2/L3 on the inverter: all of the charge is on the busiest phase
    c.ov.flow = lambda: {"soc": 40, "house": 1000, "pv": 0, "ev": 0, "battery": 0}
    c.ov.phase_room_a = lambda: 10.0  # 10 A left: 2.3 kW, not 6.9
    assert c.intents()["battery"]["ctx"]["power_w"] == 2300


def test_nan_is_no_reading_anywhere():
    from energy_pilot import control, overview

    for bad in ("nan", "inf", "-inf"):
        assert overview._num({"state": bad}) is None and control._num(bad) is None
    assert overview._num({"state": "4.5"}) == 4.5 and control._num("4.5") == 4.5


def test_a_frozen_meter_is_not_read():
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 11, 28, 12, tzinfo=timezone.utc)
    ents = ["sensor.l1", "sensor.l2", "sensor.l3"]
    old = (now - timedelta(minutes=20)).isoformat()
    fresh = (now - timedelta(minutes=1)).isoformat()
    st = {e: {"state": "8", "last_updated": old} for e in ents}
    assert phases.worst(st, ents, now.timestamp()) is None  # the dongle stopped: all three frozen
    st["sensor.l2"] = {"state": "9", "last_updated": fresh}
    assert phases.worst(st, ents, now.timestamp()) == 9.0  # one phase steady (nothing on it) is fine

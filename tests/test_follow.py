from datetime import datetime, timedelta

from energy_pilot.checks import FollowWatch

T0 = datetime(2026, 11, 10, 7, 17)
WANT = {"intent": "normal", "ctx": {"min_soc": 10, "target": 78}}
STUCK = {"battery": 0.0, "grid": 990.0, "house": 1000.0, "pv": 0.0, "soc": 95}
STATES = {"number.growatt_sph_free_mode_discharge_rate": {"state": "0"}, "number.growatt_sph_free_mode_charge_rate": {"state": "100"},
          "number.growatt_sph_load_first_stop_discharge": {"state": "10"}}


def test_a_battery_held_back_is_told_with_the_setting_at_zero():
    w = FollowWatch()
    for m in range(0, 11):
        w.see(T0 + timedelta(minutes=m), "control", WANT, STUCK, STATES, list(STATES))
    (c,) = w.check()
    assert c["key"] == "follow_discharge_why" and c["vals"]["list"] == "growatt_sph_free_mode_discharge_rate = 0"


def test_quiet_when_it_follows_or_in_shadow_or_not_long():
    w = FollowWatch()
    for m in range(0, 5):
        w.see(T0 + timedelta(minutes=m), "control", WANT, STUCK, STATES, list(STATES))
    assert w.check() == []  # not 10 minutes yet
    w.see(T0 + timedelta(minutes=12), "control", WANT, {**STUCK, "battery": -1000.0, "grid": 0.0}, STATES, list(STATES))
    assert w.check() == [] and w.since is None
    s = FollowWatch()
    for m in range(0, 15):
        s.see(T0 + timedelta(minutes=m), "shadow", WANT, STUCK, STATES, list(STATES))
    assert s.check() == []
    low = FollowWatch()  # the battery at its floor may stand still
    for m in range(0, 15):
        low.see(T0 + timedelta(minutes=m), "control", WANT, {**STUCK, "soc": 11}, STATES, list(STATES))
    assert low.check() == []


def test_a_limit_at_its_lowest_counts_too():
    """Sungrow's "no battery discharge" sets the max discharge power to 10 W, its minimum - not 0."""
    st = {"number.sungrow_battery_max_discharge_power": {"state": "10", "attributes": {"min": 10, "max": 5000}},
          "number.sungrow_battery_min_soc": {"state": "10", "attributes": {"min": 0, "max": 50}}}
    assert FollowWatch.suspects("discharge", st, list(st)) == ["sungrow_battery_max_discharge_power = 10"]


def test_a_number_is_kept_inside_what_the_entity_takes():
    from types import SimpleNamespace

    from energy_pilot.control import Controller

    c = Controller.__new__(Controller)
    c.ha = SimpleNamespace(states={"number.sg_battery_max_discharge_power": {"state": "10", "attributes": {"min": 10, "max": 5000}},
                                   "number.growatt_sph_free_mode_discharge_rate": {"state": "0", "attributes": {"min": 0, "max": 100}}})
    call = lambda e, v: {"domain": "number", "service": "set_value", "data": {"entity_id": e, "value": v}}  # noqa: E731
    assert c._clamp([call("number.sg_battery_max_discharge_power", 6000)])[0]["data"]["value"] == 5000
    assert c._clamp([call("number.growatt_sph_free_mode_discharge_rate", 100)])[0]["data"]["value"] == 100
    sw = {"domain": "switch", "service": "turn_off", "data": {"entity_id": "switch.x"}}
    assert c._clamp([sw]) == [sw]


def test_modes_that_stop_the_battery_are_named():
    st = {"select.victron_system_ess_batterylife_state": {"state": "Keep batteries charged"},
          "select.givenergy_battery_pause_mode": {"state": "Not Paused"},
          "switch.victron_ess_disable_charge": {"state": "on"}}
    assert FollowWatch.suspects("discharge", st, list(st)) == ["victron_system_ess_batterylife_state = Keep batteries charged"]
    assert FollowWatch.suspects("charge", st, list(st)) == ["victron_ess_disable_charge = on"]

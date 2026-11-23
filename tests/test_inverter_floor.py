from types import SimpleNamespace

from energy_pilot.checks import FollowWatch, inverter_floor, inverter_floors

STATES = {
    "number.deye_inverter_battery_low_soc": {"state": "15", "attributes": {"unit_of_measurement": "%"}},
    "number.deye_inverter_battery_shutdown_soc": {"state": "10", "attributes": {"unit_of_measurement": "%"}},
    "number.deye_inverter_battery_restart_soc": {"state": "30", "attributes": {"unit_of_measurement": "%"}},
    "number.deye_inverter_program_1_soc": {"state": "50", "attributes": {"unit_of_measurement": "%"}},
    "number.deye_inverter_battery_low_voltage": {"state": "47", "attributes": {"unit_of_measurement": "V"}},
}
ENTS = list(STATES)


def test_floors_found_without_restart_and_program():
    assert sorted(inverter_floors(STATES, ENTS)) == [("deye_inverter_battery_low_soc", 15.0), ("deye_inverter_battery_shutdown_soc", 10.0)]
    assert ("deye_inverter_battery_restart_soc", 30.0) in inverter_floors(STATES, ENTS, restart=True)


def test_kostal_minimum_soc_limit_is_a_floor():
    st = {"number.plenticore_l_g3_battery_minimum_soc_limit": {"state": "30", "attributes": {"unit_of_measurement": "%"}},
          "number.plenticore_l_g3_battery_maximum_soc_limit": {"state": "90", "attributes": {"unit_of_measurement": "%"}}}
    assert inverter_floors(st, list(st)) == [("plenticore_l_g3_battery_minimum_soc_limit", 30.0)]


def _engine(mode="control"):
    ctl = SimpleNamespace(mode=lambda part: mode, entities={"battery": ENTS})
    return SimpleNamespace(ov=SimpleNamespace(controller=ctl, ha=SimpleNamespace(states=STATES)))


def test_check_offers_inverter_level():
    out = inverter_floor(_engine(), SimpleNamespace(min_soc=10))
    assert out[0]["key"] == "inv_floor" and out[0]["vals"]["inv"] == 15 and out[0]["fix"] == {"battery_min_soc": 15}
    assert inverter_floor(_engine(), SimpleNamespace(min_soc=15)) == []
    assert inverter_floor(_engine("shadow"), SimpleNamespace(min_soc=10)) == []


def test_follow_watch_names_the_floor():
    s = FollowWatch.suspects("discharge", STATES, ENTS, soc=15)
    assert "deye_inverter_battery_low_soc = 15 %" in s and "deye_inverter_battery_restart_soc = 30 %" in s
    assert not any("shutdown" in x for x in s)

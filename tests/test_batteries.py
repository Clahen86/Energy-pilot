"""More than one home battery: planned as one, found by itself."""

from energy_pilot import batteries


def st(v, unit="%", dc="battery", name=None):
    return {"state": str(v), "attributes": {"unit_of_measurement": unit, "device_class": dc, "friendly_name": name}}


STATES = {
    "sensor.solaredge_b1_state_of_energy": st(40, name="SolarEdge battery"),
    "sensor.solaredge_b1_dc_power": st(-1500, "W", "power"),
    "sensor.victron_battery_soc": st(80, name="Victron battery SoC"),
    "sensor.victron_battery_power": st(2.0, "kW", "power"),
    "sensor.victron_ac_power": st(500, "W", "power"),
    "sensor.pixel_8_battery_level": st(55),
    "sensor.claus_battery_level": st(70),
    "sensor.kitchen_motion_battery": st(90),
}


def test_level_weighted_by_size_and_powers_added():
    main = {"soc": 40, "power": -1500, "kwh": 24}
    other = batteries.read(STATES, {"soc": "sensor.victron_battery_soc", "power": "sensor.victron_battery_power", "kwh": 32})
    assert other["power"] == 2000
    soc, w = batteries.combine(main, [other])
    assert soc == round((40 * 24 + 80 * 32) / 56, 1) and w == 500


def test_unknown_level_leaves_the_total_unknown():
    soc, _ = batteries.combine({"soc": None, "power": 0, "kwh": 10}, [{"soc": 50, "power": None, "kwh": 10}])
    assert soc is None


def test_finds_the_victron_not_the_phone_or_the_motion_sensor():
    found = batteries.find(STATES, "sensor.solaredge_b1_state_of_energy", [], [])
    assert found == [{"soc": "sensor.victron_battery_soc", "power": "sensor.victron_battery_power", "name": "Victron battery SoC"}]
    assert batteries.find(STATES, "sensor.solaredge_b1_state_of_energy", [], ["sensor.victron_battery_soc"]) == []
    assert batteries.find(STATES, "sensor.solaredge_b1_state_of_energy", ["sensor.victron_battery_soc"], []) == []


def test_extras_need_a_level_sensor():
    assert batteries.extras({"batteries": [{"name": "x", "soc": ""}, {"soc": "sensor.victron_battery_soc"}]}) == [{"soc": "sensor.victron_battery_soc"}]

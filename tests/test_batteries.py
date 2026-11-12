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


def test_a_phone_with_a_battery_power_sensor_is_not_a_home_battery():
    # The Android companion app has "Battery power" beside the level - it looked like a home battery.
    s = {**STATES, "sensor.sm_g998b_battery_level": st(80, name="SM-G998B Battery level"),
         "sensor.sm_g998b_battery_power": st(2.1, "W", "power")}
    main = "sensor.solaredge_b1_state_of_energy"
    taken = ["sensor.victron_battery_soc"]
    assert [f["soc"] for f in batteries.find(s, main, taken, [])] == ["sensor.sm_g998b_battery_level"]
    assert batteries.find(s, main, taken, [], {"sensor.sm_g998b_battery_level", "sensor.sm_g998b_battery_power"}) == []


def test_extras_need_a_level_sensor():
    assert batteries.extras({"batteries": [{"name": "x", "soc": ""}, {"soc": "sensor.victron_battery_soc"}]}) == [{"soc": "sensor.victron_battery_soc"}]


def _ctl(settings):
    from types import SimpleNamespace

    from energy_pilot.control import Controller

    c = Controller.__new__(Controller)
    c.ov = SimpleNamespace(settings=settings, role=lambda r: None)
    c.entities = {"battery": ["switch.ess_force_charge", "number.ess_maximum_charge_power", "number.ess_maximum_discharge_power"],
                  "bat2": ["number.solaredge_i1_storage_command_mode"]}
    c.platforms = {"battery": "victron", "bat2": "solaredge_modbus_multi"}
    c.bat_info = {"bat2": {"device": "dev2", "model": "SE10K", "serial": "S2"}}
    c.services, c.model = None, None
    return c


def test_power_shared_by_size_and_each_holds_its_own_level():
    st = {"battery_charge_kw": 8, "battery_discharge_kw": 4, "inverter_profile": "victron",
          "batteries": [{"soc": "sensor.b2", "charge_kw": 4, "discharge_kw": 4, "profile": "solaredge_modbus_multi"}]}
    c = _ctl(st)
    want = {"intent": "charge", "ctx": {"min_soc": 10, "soc": 50, "target": 80, "rate": 100, "power_w": 12000, "power_kw": 12.0,
                                        "max_power_w": 8000, "max_power_kw": 8.0, "max_charge_w": 12000, "max_charge_kw": 12.0,
                                        "export_w": 0, "device_id": "", "serial": ""}}
    out = c._share(want, {"batteries": [{"soc": 40}, {"soc": 70}]})
    assert out["battery"]["ctx"]["power_w"] == 8000 and out["bat2"]["ctx"]["power_w"] == 4000
    assert out["battery"]["ctx"]["max_power_w"] == 4000 and out["bat2"]["ctx"]["max_power_w"] == 4000
    assert out["battery"]["ctx"]["soc"] == 40 and out["bat2"]["ctx"]["soc"] == 70 and out["bat2"]["ctx"]["target"] == 80
    assert out["bat2"]["ctx"]["device_id"] == "dev2"


def test_each_battery_has_its_own_profile():
    c = _ctl({"inverter_profile": "victron", "batteries": [{"soc": "sensor.b2", "profile": "solaredge_modbus_multi"}]})
    assert c.bat_parts() == ["bat2"]
    assert c.profile_key("bat2") == "solaredge_modbus_multi" and c.profile_key() == "victron"
    assert c._pool("bat2") == ["number.solaredge_i1_storage_command_mode"]

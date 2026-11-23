"""#50-#53 from the nightly training: Deye LP1 hold, SolarEdge hold and flash writes, Anker's own integration, FoxESS."""

from energy_pilot.adapters import PROFILES, fill, guess_profile, resolve

CTX = {"soc": 46, "min_soc": 10, "target": 80, "power_w": 3000, "charge_a": 20, "max_power_w": 5000, "max_charge_w": 5000}


def _calls(key, intent, ents):
    return {(c["data"].get("entity_id"), c["data"].get("option", c["data"].get("value"))) for c in resolve(PROFILES[key][intent], ents, CTX)}


def test_deye_holds_just_above_the_level_now():
    assert fill("{hold_soc}", {"soc": 46}) == 47 and fill("{hold_soc}", {"soc": 100}) == 100
    ents = [f"number.deye_program_{n}_soc" for n in range(1, 7)] + [f"select.deye_program_{n}_charging" for n in range(1, 7)]
    assert ("number.deye_program_1_soc", 47) in _calls("solarman", "hold", ents)


def test_solaredge_hold_stops_discharging_and_keeps_the_flash():
    ents = ["select.se_storage_control_mode", "select.se_storage_default_mode", "select.se_storage_command_mode",
            "number.se_storage_command_timeout", "number.se_storage_discharge_limit", "number.se_storage_charge_limit"]
    c = _calls("solaredge_modbus_multi", "hold", ents)
    assert ("number.se_storage_discharge_limit", 0) in c and ("select.se_storage_command_mode", "Maximize Self Consumption") in c
    import re
    only = PROFILES["solaredge_modbus_multi"]["keepalive_only"]
    assert not any(re.search(r, "select.se_storage_control_mode") for r in only)  # flash: never written on time
    assert any(re.search(r, "number.se_storage_command_timeout") for r in only)


def test_anker_official_is_picked_and_steered():
    ents = ["select.sb4_operating_mode_device_runs_by_command_in_third_party_controlled", "select.sb4_grid_flow",
            "number.sb4_power_control", "number.sb4_charging_limit"]
    assert guess_profile(ents, {"anker_solix_official"}) == "anker_solix_official"
    c = _calls("anker_solix_official", "export", ents)
    assert ("select.sb4_grid_flow", "discharge") in c and ("number.sb4_power_control", 3000) in c


def test_read_only_batteries_keep_the_other_checks():
    # READ_ONLY was defined twice, the 3-tuples won, and "alt, why = READ_ONLY[plat]" failed for Powerwall, Solis, SEMS
    # homes - checks.run() raised and every other check was lost with it
    from energy_pilot import checks
    assert all(len(v) == 2 for v in checks.BATTERY_READ_ONLY.values())
    assert all(len(v) == 3 for v in checks.READ_ONLY.values()) and "solax" in checks.READ_ONLY


def test_wallbox_pause_resume_is_turned_on_to_charge():
    from energy_pilot.adapters import charger_calls
    ents = ["switch.wb_pause_resume", "number.wb_maximum_charging_current"]
    calls = charger_calls("charge", ents, None, 16, switch="switch.wb_pause_resume")
    assert {"domain": "switch", "service": "turn_on", "data": {"entity_id": "switch.wb_pause_resume"}} in calls
    calls = charger_calls("charge", ["switch.x_charging_pause"], None, 16, switch="switch.x_charging_pause")
    assert calls[-1]["service"] == "turn_off"  # a plain "pause" switch: off = charging, as before


def test_old_solarman_and_kostal_get_the_integration_that_controls_them():
    from types import SimpleNamespace
    from energy_pilot import checks
    def eng(reg, soc, prof=None):
        ctl = SimpleNamespace(_ent_reg=reg, profile_key=lambda part: prof)
        return SimpleNamespace(ov=SimpleNamespace(controller=ctl, role=lambda r: soc))
    reg = {"sensor.deye_battery": {"platform": "solarman"}}
    out = checks.read_only(eng(reg, "sensor.deye_battery", prof="solarman"), {})
    assert out and out[0]["vals"]["use"] == "Solarman (davidrapan)"
    reg["number.deye_program_1_soc"] = {"platform": "solarman"}
    assert checks.read_only(eng(reg, "sensor.deye_battery", prof="solarman"), {}) == []  # the new one: nothing to say
    out = checks.read_only(eng({"sensor.k_soc": {"platform": "kostal_plenticore"}}, "sensor.k_soc"), {})
    assert out[0]["vals"]["name"] == "Kostal"


def test_new_profiles_are_picked_and_steered():
    gen3 = ["select.sx_charger_use_mode", "select.sx_allow_grid_charge", "number.sx_battery_minimum_capacity",
            "number.sx_forcetime_period_1_max_capacity", "time.sx_charge_start_1", "time.sx_charge_end_1"]
    assert guess_profile(gen3, {"solax_modbus"}) == "solax_modbus_gen3"
    gen4 = ["select.sx_charger_use_mode", "select.sx_manual_mode_select"]
    assert guess_profile(gen4, {"solax_modbus"}) == "solax_modbus"
    c = [x for x in resolve(PROFILES["solax_modbus_gen3"]["charge"], gen3, {**CTX, "lease_from": "02:00", "lease_to": "06:00"}) if x["domain"] == "time"]
    assert len(c) == 2 and c[0]["service"] == "set_value" and c[0]["data"]["time"].count(":") == 2
    srne = ["select.srne_output_priority_0xe204", "select.srne_charger_source_priority_0xe20f", "number.ac_charging_current_limit_0xe205"]
    assert guess_profile(srne, {"esphome"}) == "offgrid_esphome"
    assert ("select.mk_operating_mode", "auto") in _calls("marstek", "normal", ["select.mk_operating_mode"])
    z = ["select.zendure_manager_operation", "number.zendure_manager_manual_power"]
    assert ("number.zendure_manager_manual_power", -3000) in _calls("zendure_ha", "charge", z)

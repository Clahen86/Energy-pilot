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

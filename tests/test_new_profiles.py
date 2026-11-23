"""Profiles built from users' setups (the stats' entity lists) and the integrations' own code."""

from energy_pilot import adapters
from energy_pilot.adapters import PROFILES, guess_profile, resolve
from energy_pilot.control import YAML_CONTROLS

CTX = {"soc": 46, "min_soc": 10, "target": 80, "power_w": 3000, "rate": 60, "device_id": "dev1"}


def _calls(key, intent, ents):
    return [(c["service"], c["data"].get("entity_id"), c["data"].get("option", c["data"].get("value"))) for c in resolve(PROFILES[key][intent], ents, CTX)]


def test_mkaiser_template_controls_are_picked_up_and_matched():
    assert YAML_CONTROLS.match("select.ems_mode") and YAML_CONTROLS.match("number.battery_forced_charge_discharge_power")
    assert not YAML_CONTROLS.match("select.ems_mode_other")
    ents = ["select.ems_mode", "select.battery_forced_charge_discharge", "number.battery_forced_charge_discharge_power"]
    assert ("select_option", "select.battery_forced_charge_discharge", "Forced charge") in _calls("sungrow", "charge", ents)
    # normal puts the forced command back to Stop as well - else it kept charging from the grid (issue #42)
    n = _calls("sungrow", "normal", ents)
    assert n[0] == ("select_option", "select.battery_forced_charge_discharge", "Stop (default)")
    assert ("select_option", "select.ems_mode", "Self-consumption mode (default)") in n


def test_sungrow_hass_by_its_translated_battery_mode():
    ents = ["select.vekselretter_batteritilstand", "number.vekselretter_effekt"]
    adapters.ALIASES = {ents[0]: "select.tk_battery_mode", ents[1]: "number.tk_charge_discharge_power"}
    try:
        c = _calls("sungrow_hass", "charge", ents)
        assert ("set_value", ents[1], 3000) in c and ("select_option", ents[0], "re:force.?charge") in c
    finally:
        adapters.ALIASES = {}


def test_libbi_marstek_luxpower_e3dc():
    lib = ["select.myenergi_libbi_123_operating_mode", "switch.myenergi_libbi_123_charge_from_grid", "number.myenergi_libbi_123_charge_target"]
    assert ("select_option", lib[0], "Stopped") in _calls("myenergi_libbi", "hold", lib)
    assert ("set_value", lib[2], 80) in _calls("myenergi_libbi", "charge", lib)
    mv = ["switch.venus_manual_mode", "switch.venus_rs485_control_mode", "select.venus_force_mode", "number.venus_set_charge_power"]
    assert ("set_value", mv[3], 3000) in _calls("marstek_venus", "charge", mv)
    lx = ["switch.ac_charging", "switch.forced_discharge", "number.on_grid_cut_off_soc", "number.ac_charge_power", "number.ac_charge_end_soc"]
    assert ("set_value", "number.on_grid_cut_off_soc", 46) in _calls("luxpower", "hold", lx)
    e3 = resolve(PROFILES["e3dc_rscp"]["charge"], [], CTX)[0]
    assert e3["domain"] == "e3dc_rscp" and e3["data"]["power_value"] == 3000 and e3["data"]["device_id"] == "dev1"
    assert guess_profile(["select.myenergi_libbi_123_operating_mode"], {"myenergi"}) in (None, "myenergi_libbi")

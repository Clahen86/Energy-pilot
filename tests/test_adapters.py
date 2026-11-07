"""Adapters: the same intents become the right calls for each brand."""

from energy_pilot import adapters

GROWATT = ["select.growatt_sph_work_mode_priority", "number.growatt_sph_load_first_stop_discharge", "select.growatt_sph_battery_first_grid_charge",
           "switch.growatt_sph_battery_first_slot_1_enabled", "select.growatt_sph_battery_first_slot_1_start", "select.growatt_sph_battery_first_slot_1_end",
           "number.growatt_sph_battery_first_charge_rate", "number.growatt_sph_battery_first_stop_charge", "select.growatt_blaeser_adfaerd_ved_taending"]
CTX = {"min_soc": 10, "soc": 62, "target": 90, "rate": 80, "power_w": 2400, "max_power_w": 3000}


def test_growatt_from_your_entities():
    assert adapters.guess_profile(GROWATT, {"mqtt"}) == "growatt"
    p = adapters.PROFILES["growatt"]
    hold = adapters.resolve(p["hold"], GROWATT, CTX)
    assert {"domain": "number", "service": "set_value", "data": {"entity_id": "number.growatt_sph_load_first_stop_discharge", "value": 62}} in hold
    charge = adapters.resolve(p["charge"], GROWATT, CTX)
    assert charge[-1]["data"] == {"entity_id": "select.growatt_sph_work_mode_priority", "option": "Battery first"}
    assert {"entity_id": "number.growatt_sph_battery_first_stop_charge", "value": 90} in [c["data"] for c in charge]
    normal = adapters.resolve(p["normal"], GROWATT, CTX)
    assert normal[0]["data"]["option"] == "Load first" and normal[1]["data"]["value"] == 10


def test_other_brands_and_custom():
    solax = ["select.solax_charger_use_mode", "select.solax_manual_mode_select"]
    assert adapters.guess_profile(solax, {"solax_modbus"}) == "solax_modbus"
    hold = adapters.resolve(adapters.PROFILES["solax_modbus"]["hold"], solax, CTX)
    assert [c["data"]["option"] for c in hold] == ["Manual Mode", "Stop Charge and Discharge"]
    huawei = adapters.resolve(adapters.PROFILES["huawei_solar"]["charge"], [], CTX)
    assert huawei == [{"domain": "huawei_solar", "service": "forcible_charge_soc", "data": {"target_soc": 90, "power": 2400}}]
    custom = adapters.resolve([("select.my_inverter_mode", "select", "Force"), ("number.my_target", "number", "{target}")],
                              ["select.my_inverter_mode", "number.my_target"], CTX)
    assert custom[1]["data"] == {"entity_id": "number.my_target", "value": 90}


def test_chargers():
    easee = ["switch.easee_is_enabled", "number.easee_dynamic_limit"]
    calls = adapters.charger_calls("charge", easee, "easee", 16)
    assert calls[0]["data"] == {"entity_id": "number.easee_dynamic_limit", "value": 16} and calls[1]["service"] == "turn_on"
    assert adapters.charger_calls("stop", easee, "easee", 16)[0]["service"] == "turn_off"
    keba = adapters.charger_calls("charge", [], "keba", 10)
    assert keba[0] == {"domain": "keba", "service": "set_current", "data": {"current": 10}}
    paused = adapters.charger_calls("charge", ["switch.charger_pause"], None, 16)
    assert paused[0]["service"] == "turn_off"  # a "pause" switch is turned off to charge


def test_model_picks_the_variant():
    tlxh = ["select.growatt_inverter_priority", "number.growatt_discharge_stop_soc", "switch.growatt_ac_charge",
            "number.growatt_charge_stop_soc", "number.growatt_charge_power_rate"]
    assert adapters.guess_profile(tlxh, {"growatt_local"}, "MOD 10KTL3-XH") == "growatt_tlxh"
    assert adapters.guess_profile(GROWATT, {"mqtt"}, "SPH 6000TL3 BH") == "growatt"
    charge = adapters.resolve(adapters.PROFILES["growatt_tlxh"]["charge"], tlxh, CTX)
    assert {"domain": "switch", "service": "turn_on", "data": {"entity_id": "switch.growatt_ac_charge"}} in charge


def test_missing_control_is_found_and_never_half():
    p = adapters.PROFILES["growatt"]
    steps = {i: p[i] for i in ("normal", "hold", "charge")}
    assert adapters.missing(adapters.check(steps, GROWATT)) == []
    partial = [e for e in GROWATT if "stop_charge" not in e]
    res = adapters.check(steps, partial)
    assert adapters.missing(res) == [r"number\..*battery_first_stop_charge$"]
    # optional controls may be missing; a service that isn't there is missing
    h = adapters.PROFILES["huawei_solar"]
    hs = {i: h[i] for i in ("normal", "hold", "charge")}
    found = ["number.huawei_maximum_discharging_power"]
    assert adapters.missing(adapters.check(hs, found, h["optional"], {"huawei_solar.forcible_charge_soc"})) == []
    assert adapters.missing(adapters.check(hs, found, h["optional"], set())) == ["huawei_solar.forcible_charge_soc"]

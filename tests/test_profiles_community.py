from energy_pilot.adapters import PROFILES, guess_profile, resolve

GROWATT = ["number.min_battery_charge_power_limit", "number.min_battery_charge_soc_limit",
           "number.min_battery_discharge_power_limit", "number.min_battery_discharge_soc_limit",
           "number.min_battery_discharge_soc_limit_on_grid", "switch.min_charge_from_grid"]


def test_growatt_cloud_profile_found_and_steps():
    assert guess_profile(GROWATT, {"growatt_server"}, "Growatt") == "growatt_server"
    ctx = {"min_soc": 10, "soc": 55, "target": 90, "rate": 80}
    hold = resolve(PROFILES["growatt_server"]["hold"], GROWATT, ctx)
    assert {"domain": "number", "service": "set_value", "data": {"entity_id": "number.min_battery_discharge_soc_limit_on_grid", "value": 55}} in hold
    charge = resolve(PROFILES["growatt_server"]["charge"], GROWATT, ctx)
    assert any(c["service"] == "turn_on" and c["data"]["entity_id"] == "switch.min_charge_from_grid" for c in charge)


def test_foxess_hold_keeps_self_use():
    ents = ["select.foxh3pro_work_mode", "number.foxh3pro_min_soc_on_grid", "number.foxh3pro_force_charge_power"]
    hold = resolve(PROFILES["foxess_modbus"]["hold"], ents, {"soc": 61, "min_soc": 10})
    assert {"domain": "number", "service": "set_value", "data": {"entity_id": "number.foxh3pro_min_soc_on_grid", "value": 61}} in hold
    assert not any(c["data"].get("option") == "Back-up" for c in hold)


def test_foxess_force_power_in_kw():
    ents = ["select.fox_ess_h1_work_mode", "number.fox_ess_h1_force_discharge_power", "number.fox_ess_h1_force_charge_power",
            "number.fox_ess_h1_min_soc_on_grid"]
    out = resolve(PROFILES["foxess_modbus"]["export"], ents, {"power_w": 1000, "power_kw": 1.0})
    assert {"entity_id": "number.fox_ess_h1_force_discharge_power", "value": 1.0} in [c["data"] for c in out]
    out = resolve(PROFILES["foxess_modbus"]["charge"], ents, {"power_w": 2500, "power_kw": 2.5, "target": 90})
    assert {"entity_id": "number.fox_ess_h1_force_charge_power", "value": 2.5} in [c["data"] for c in out]

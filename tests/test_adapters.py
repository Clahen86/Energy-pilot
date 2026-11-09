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
    huawei = adapters.resolve(adapters.PROFILES["huawei_solar"]["charge"], [], {**CTX, "device_id": "abc123"})
    assert huawei == [{"domain": "huawei_solar", "service": "forcible_charge_soc", "data": {"device_id": "abc123", "target_soc": 90, "power": 2400}}]
    custom = adapters.resolve([("select.my_inverter_mode", "select", "Force"), ("number.my_target", "number", "{target}")],
                              ["select.my_inverter_mode", "number.my_target"], CTX)
    assert custom[1]["data"] == {"entity_id": "number.my_target", "value": 90}


def test_chargers():
    generic = ["switch.mycharger_is_enabled", "number.mycharger_dynamic_limit"]
    calls = adapters.charger_calls("charge", generic, "some_charger", 16)
    assert calls[0]["data"] == {"entity_id": "number.mycharger_dynamic_limit", "value": 16} and calls[1]["service"] == "turn_on"
    assert adapters.charger_calls("stop", generic, "some_charger", 16)[0]["service"] == "turn_off"
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
    found = ["number.batteries_maximum_discharging_power"]
    assert adapters.missing(adapters.check(hs, found, h["optional"], {"huawei_solar.forcible_charge_soc"})) == []
    assert adapters.missing(adapters.check(hs, found, h["optional"], set())) == ["huawei_solar.forcible_charge_soc"]


def test_deye_solarman_sets_all_six_programmes():
    deye = (["select.deye_time_of_use", "switch.deye_battery_grid_charging", "select.deye_work_mode"]
            + [f"number.deye_program_{n}_soc" for n in range(1, 7)] + [f"select.deye_program_{n}_charging" for n in range(1, 7)])
    assert adapters.guess_profile(deye, {"solarman"}) == "solarman"
    p = adapters.PROFILES["solarman"]
    steps = {i: p[i] for i in ("normal", "hold", "charge")}
    assert adapters.missing(adapters.check(steps, deye)) == []
    charge = adapters.resolve(p["charge"], deye, CTX)
    assert {"entity_id": "number.deye_program_4_soc", "value": 90} in [c["data"] for c in charge]
    assert {"entity_id": "select.deye_program_6_charging", "option": "Grid"} in [c["data"] for c in charge]
    assert {"domain": "switch", "service": "turn_on", "data": {"entity_id": "switch.deye_battery_grid_charging"}} in charge
    hold = adapters.resolve(p["hold"], deye, CTX)
    assert {"entity_id": "number.deye_program_1_soc", "value": 62} in [c["data"] for c in hold]


def test_victron_ess():
    vic = ["number.ess_ac_grid_setpoint", "switch.ess_force_charge", "number.ess_maximum_charge_power", "number.ess_maximum_discharge_power"]
    assert adapters.guess_profile(vic, {"victron"}) == "victron"
    p = adapters.PROFILES["victron"]
    steps = {i: p[i] for i in ("normal", "hold", "charge")}
    assert adapters.missing(adapters.check(steps, vic)) == []
    charge = adapters.resolve(p["charge"], vic, CTX)
    assert {"entity_id": "number.ess_maximum_charge_power", "value": 2400} in [c["data"] for c in charge]
    assert charge[-1] == {"domain": "switch", "service": "turn_on", "data": {"entity_id": "switch.ess_force_charge"}}
    hold = adapters.resolve(p["hold"], vic, CTX)
    assert {"entity_id": "number.ess_maximum_discharge_power", "value": 0} in [c["data"] for c in hold]
    assert all("grid_setpoint" not in str(c) for i in steps for c in adapters.resolve(p[i], vic, CTX))  # his own setpoint stays


def test_ecoflow_powerstream_gives_the_house_its_watts():
    eco = ["number.powerstream_rooster_custom_load_power_settings", "number.powerstream_rooster_max_charge_level",
           "number.powerstream_rooster_min_discharge_level"]
    assert adapters.guess_profile(eco, set()) == "ecoflow"
    p = adapters.PROFILES["ecoflow"]
    assert p["grid_charge"] is False
    steps = {i: p[i] for i in ("normal", "hold", "charge")}
    assert adapters.missing(adapters.check(steps, eco)) == []
    normal = adapters.resolve(p["normal"], eco, {**CTX, "house_w": 450})
    assert {"entity_id": "number.powerstream_rooster_custom_load_power_settings", "value": 450} in [c["data"] for c in normal]
    hold = adapters.resolve(p["hold"], eco, CTX)
    assert {"entity_id": "number.powerstream_rooster_custom_load_power_settings", "value": 0} in [c["data"] for c in hold]


def test_deye_esphome_klatremis():
    d = (["switch.deye_time_of_use", "switch.deye_grid_charge", "switch.deye_solar_sell", "select.deye_energy_priority"]
         + [f"number.deye_time_point_{n}_capacity" for n in range(1, 7)] + [f"switch.deye_time_point_{n}_charge_enable" for n in range(1, 7)])
    assert adapters.guess_profile(d, {"esphome"}) == "deye_esphome"
    p = adapters.PROFILES["deye_esphome"]
    steps = {i: p[i] for i in ("normal", "hold", "charge")}
    assert adapters.missing(adapters.check(steps, d)) == []
    charge = adapters.resolve(p["charge"], d, CTX)
    assert {"entity_id": "number.deye_time_point_3_capacity", "value": 90} in [c["data"] for c in charge]
    assert {"domain": "switch", "service": "turn_on", "data": {"entity_id": "switch.deye_time_point_6_charge_enable"}} in charge


def test_sofar_passive_mode():
    so = ["select.inverter_storage_control_mode", "number.inverter_passive_minimum_battery_power",
          "number.inverter_passive_maximum_battery_power", "select.inverter_timed_control"]
    assert adapters.guess_profile(so, {"solarman"}) == "sofar"
    p = adapters.PROFILES["sofar"]
    steps = {i: p[i] for i in ("normal", "hold", "charge")}
    assert adapters.missing(adapters.check(steps, so)) == []
    charge = adapters.resolve(p["charge"], so, CTX)
    assert [c["data"].get("value", c["data"].get("option")) for c in charge] == [2400, 2400, "Passive"]
    hold = adapters.resolve(p["hold"], so, {**CTX, "max_charge_w": 3000})
    assert [c["data"].get("value", c["data"].get("option")) for c in hold] == [0, 3000, "Passive"]
    assert adapters.resolve(p["normal"], so, CTX)[0]["data"]["option"] == "Self Use"



def test_profiles_from_the_integrations_own_names():
    """Entity names as the integrations create them (from their source code)."""
    cases = {
        "huawei_solar": (["select.batteries_working_mode", "number.batteries_maximum_discharging_power", "button.batteries_stop_forcible_charge",
                          "select.emma_ess_control_mode"], "hold", "select.batteries_working_mode", "Maximise self consumption"),
        "solaredge_modbus_multi": (["select.solaredge_b1_storage_control_mode", "select.solaredge_b1_storage_command_mode", "select.solaredge_b1_ac_charge_policy",
                                    "number.solaredge_b1_storage_charge_limit", "number.solaredge_b1_storage_command_timeout"],
                                   "charge", "select.solaredge_b1_ac_charge_policy", "Always Allowed"),
        "foxess_modbus": (["select.work_mode", "number.force_charge_power", "number.force_charge_max_soc"], "charge", "number.force_charge_max_soc", 90),
        "sigen": (["switch.sigen_plant_remote_ems_controlled_by_home_assistant", "select.sigen_plant_remote_ems_control_mode",
                   "number.sigen_plant_ess_max_charging_limit"], "charge", "number.sigen_plant_ess_max_charging_limit", 2.4),
        "sofar_solax": (["select.sofar_energy_storage_mode", "number.sofar_passive_mode_battery_power_min", "number.sofar_passive_mode_battery_power_max"],
                        "charge", "select.sofar_energy_storage_mode", "Passive Mode"),
        "tesla": (["number.my_home_backup_reserve", "switch.my_home_allow_charging_from_grid", "select.my_home_operation_mode"],
                  "charge", "number.my_home_backup_reserve", 90),
        "enphase_envoy": (["select.enpower_482_storage_mode", "number.enpower_482_reserve_battery_level", "switch.enpower_482_charge_from_grid"],
                          "hold", "number.enpower_482_reserve_battery_level", 62),
    }
    ctx = {**CTX, "power_kw": 2.4, "max_charge_kw": 3.0, "max_charge_w": 3000, "device_id": "d1"}
    for key, (ents, intent, entity, want) in cases.items():
        p = adapters.PROFILES[key]
        steps = {i: p[i] for i in ("normal", "hold", "charge")}
        assert adapters.missing(adapters.check(steps, ents, p.get("optional"), {"huawei_solar.forcible_charge_soc"})) == [], key
        calls = adapters.resolve(p[intent], ents, ctx)
        got = {c["data"].get("entity_id"): c["data"].get("option", c["data"].get("value")) for c in calls}
        assert got.get(entity) == want, (key, got)
    # emma's control mode is not the battery's working mode
    assert "select.emma_ess_control_mode" not in str(adapters.resolve(adapters.PROFILES["huawei_solar"]["hold"], cases["huawei_solar"][0], ctx))


def test_givenergy_solis_alphaess_from_their_code():
    ctx = {**CTX, "device_id": "dev9", "serial": "AL123"}
    ge = ["select.givenergy_ce123_battery_pause_mode", "number.givenergy_ce123_battery_charge_power_limit"]
    p = adapters.PROFILES["givenergy_local"]
    charge = adapters.resolve(p["charge"], ge, ctx)
    svc = [c for c in charge if c["domain"] == "givenergy_local"][0]
    assert svc["service"] == "enable_timed_charge" and svc["data"] == {"device_id": "dev9", "start_time": "00:00", "end_time": "23:59", "charge_target": 90}
    hold = adapters.resolve(p["hold"], ge, ctx)
    assert {"entity_id": "select.givenergy_ce123_battery_pause_mode", "option": "Pause Discharge"} in [c["data"] for c in hold]

    so = ["select.solis_rc_force_charge_discharge", "number.solis_rc_force_battery_charge_power", "number.solis_rc_timeout"]
    p = adapters.PROFILES["solis_modbus"]
    assert adapters.missing(adapters.check({i: p[i] for i in ("normal", "hold", "charge")}, so)) == []
    assert p["reassert_s"] <= 1200  # its remote control times out after 30 min
    charge = adapters.resolve(p["charge"], so, ctx)
    assert [c["data"].get("option", c["data"].get("value")) for c in charge] == ["Solis RC Force Battery Charge", 2400, 30]

    a = adapters.resolve(adapters.PROFILES["alphaess"]["charge"], [], ctx)[0]
    assert a["service"] == "setbatterycharge" and a["data"]["serial"] == "AL123" and a["data"]["chargestopsoc"] == 90 and a["data"]["enabled"] is True


def test_service_only_profile_is_found_by_its_integration():
    assert adapters.guess_profile(["sensor.alphaess_soc"], {"alphaess"}) == "alphaess"



def test_chargers_from_their_integrations_code():
    easee = adapters.charger_calls("charge", [], "easee", 16, "devE")
    assert easee[0] == {"domain": "easee", "service": "set_charger_dynamic_limit", "data": {"device_id": "devE", "current": 16}}
    assert adapters.charger_calls("stop", [], "easee", 16, "devE")[0]["data"]["action_command"] == "pause"
    z = ["number.zaptec_installation_available_current", "button.zaptec_go_resume_charging", "button.zaptec_go_stop_charging"]
    assert [c["service"] for c in adapters.charger_calls("charge", z, "zaptec", 10)] == ["set_value", "press"]
    assert adapters.charger_calls("stop", z, "zaptec", 10)[0]["data"]["entity_id"] == "button.zaptec_go_stop_charging"
    goe = ["number.goe_123_amp", "select.goe_123_frc", "number.goe_123_lot_amp"]
    assert [c["data"].get("option", c["data"].get("value")) for c in adapters.charger_calls("charge", goe, "goecharger_api2", 12)] == [12, "2"]
    wb = ["number.wallbox_pulsar_maximum_charging_current", "switch.wallbox_pulsar_pause_resume"]
    assert adapters.charger_calls("stop", wb, "wallbox", 16)[0]["service"] == "turn_off"  # off = paused for Wallbox
    oc = ["number.charger_maximum_current", "switch.charger_charge_control"]
    assert adapters.charger_calls("charge", oc, "ocpp", 16)[1]["service"] == "turn_on"
    al = ["number.alfen_power_connector_max_current_socket_1"]
    assert adapters.charger_calls("stop", al, "alfen_wallbox", 16)[0]["data"]["value"] == 0
    assert adapters.charger_calls("charge", ["select.ohme_epod_charge_mode"], "ohme", 16)[0]["data"]["option"] == "max_charge"
    assert adapters.charger_calls("stop", ["select.myenergi_zappi_charge_mode"], "myenergi", 16)[0]["data"]["option"] == "Stopped"


def test_victron_controls_found_on_another_device():
    # Victron MQTT puts the ESS controls on an "ESS" device; the battery level comes from the GX device
    from types import SimpleNamespace

    from energy_pilot.control import Controller

    c = Controller.__new__(Controller)
    c.ov = SimpleNamespace(settings={"inverter_profile": "victron"}, role=lambda r: None)
    c.entities = {"battery": ["select.gx_device_dc_mode"]}
    c.platforms = {"battery": "victron_gx"}
    c.services, c.model = None, "GX Device"
    c.ha = SimpleNamespace(states={e: {"state": "0"} for e in (
        "switch.ess_force_charge", "number.ess_maximum_charge_power", "number.ess_maximum_discharge_power",
        "number.ess_ac_grid_setpoint", "switch.kitchen_light")})
    from energy_pilot import adapters

    assert adapters.missing(c.check()) == []
    assert "switch.kitchen_light" not in c._pool()
    assert not c.check()["export"]["missing"]

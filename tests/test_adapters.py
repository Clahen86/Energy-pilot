"""Adapters: the same intents become the right calls for each brand."""

from energy_pilot import adapters

GROWATT = ["select.growatt_sph_work_mode_priority", "number.growatt_sph_load_first_stop_discharge", "select.growatt_sph_battery_first_grid_charge",
           "switch.growatt_sph_battery_first_slot_1_enabled", "select.growatt_sph_battery_first_slot_1_start", "select.growatt_sph_battery_first_slot_1_end",
           "number.growatt_sph_battery_first_charge_rate", "number.growatt_sph_battery_first_stop_charge", "select.growatt_blaeser_adfaerd_ved_taending"]
CTX = {"min_soc": 10, "soc": 62, "soc_floor": 62, "target": 90, "rate": 80, "power_w": 2400, "max_power_w": 3000, "max_charge_w": 3000, "max_charge_kw": 3.0, "max_power_kw": 3.0,
       "lease_from": "11:15", "lease_to": "12:30"}


def test_growatt_from_your_entities():
    assert adapters.guess_profile(GROWATT, {"mqtt"}) == "growatt"
    p = adapters.PROFILES["growatt"]
    hold = adapters.resolve(p["hold"], GROWATT, CTX)
    assert {"domain": "number", "service": "set_value", "data": {"entity_id": "number.growatt_sph_load_first_stop_discharge", "value": 62}} in hold
    charge = adapters.resolve(p["charge"], GROWATT, CTX)
    assert charge[0]["data"] == {"entity_id": "select.growatt_sph_work_mode_priority", "option": "Battery first"}
    assert charge[-1]["data"]["entity_id"].endswith("battery_first_slot_1_end")  # the slot last: SolarAssistant's
    # "Battery first" is an all-day slot that would put itself over it
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
    assert adapters.missing(adapters.check(steps, GROWATT, p["optional"])) == []
    partial = [e for e in GROWATT if "stop_charge" not in e]
    res = adapters.check(steps, partial, p["optional"])
    assert adapters.missing(res) == [r"number\..*battery_first_stop_charge$"]
    # optional controls may be missing; a service that isn't there is missing
    h = adapters.PROFILES["huawei_solar"]
    hs = {i: h[i] for i in ("normal", "hold", "charge")}
    found = ["number.batteries_maximum_discharging_power"]
    assert adapters.missing(adapters.check(hs, found, h["optional"], {"huawei_solar.forcible_charge_soc", "huawei_solar.stop_forcible_charge"})) == []
    assert set(adapters.missing(adapters.check(hs, found, h["optional"], set()))) == {"huawei_solar.stop_forcible_charge", "huawei_solar.forcible_charge_soc"}


def test_deye_solarman_sets_all_six_programmes():
    deye = (["select.deye_time_of_use", "switch.deye_battery_grid_charging", "select.deye_work_mode"]
            + [f"number.deye_program_{n}_soc" for n in range(1, 7)] + [f"select.deye_program_{n}_charging" for n in range(1, 7)])
    assert adapters.guess_profile(deye, {"solarman"}) == "solarman"
    p = adapters.PROFILES["solarman"]
    steps = {i: p[i] for i in ("normal", "hold", "charge")}
    assert adapters.missing(adapters.check(steps, deye, optional=adapters.PROFILES["solarman"]["optional"])) == []
    charge = adapters.resolve(p["charge"], deye, CTX)
    assert {"entity_id": "number.deye_program_4_soc", "value": 90} in [c["data"] for c in charge]
    assert {"entity_id": "select.deye_program_6_charging", "option": "Grid"} in [c["data"] for c in charge]
    assert {"domain": "switch", "service": "turn_on", "data": {"entity_id": "switch.deye_battery_grid_charging"}} in charge
    hold = adapters.resolve(p["hold"], deye, CTX)
    assert {"entity_id": "number.deye_program_1_soc", "value": 63} in [c["data"] for c in hold]  # 1 % above (#53)


def test_victron_ess():
    vic = ["number.ess_ac_grid_setpoint", "switch.ess_force_charge", "number.ess_maximum_charge_power", "number.ess_maximum_discharge_power"]
    assert adapters.guess_profile(vic, {"victron"}) == "victron"
    p = adapters.PROFILES["victron"]
    steps = {i: p[i] for i in ("normal", "hold", "charge")}
    assert adapters.missing(adapters.check(steps, vic, p["optional"])) == []
    charge = adapters.resolve(p["charge"], vic, CTX)
    assert {"entity_id": "number.ess_maximum_charge_power", "value": 2400} in [c["data"] for c in charge]
    assert charge[-1] == {"domain": "switch", "service": "turn_on", "data": {"entity_id": "switch.ess_force_charge"}}
    hold = adapters.resolve(p["hold"], vic, CTX)
    assert {"entity_id": "number.ess_maximum_discharge_power", "value": 0} in [c["data"] for c in hold]
    assert all("grid_setpoint" not in str(c) for i in steps for c in adapters.resolve(p[i], vic, CTX))  # his own setpoint stays


def test_kostal_plenticore_battery_control():
    kos = ["switch.plenticore_l_g3_charge_start", "switch.plenticore_l_g3_discharge_start",
           "switch.plenticore_l_g3_block_charge", "switch.plenticore_l_g3_block_discharge",
           "switch.plenticore_l_g3_ems_grid_protection", "number.plenticore_l_g3_set_charge_rate",
           "number.plenticore_l_g3_set_discharge_rate", "number.plenticore_l_g3_battery_minimum_soc_limit"]
    assert adapters.guess_profile(kos, {"kostal_modbus_control"}) == "kostal_modbus_control"
    assert adapters.guess_profile(kos, set()) == "kostal_modbus_control"
    p = adapters.PROFILES["kostal_modbus_control"]
    steps = {i: p[i] for i in ("normal", "hold", "charge", "export")}
    assert adapters.missing(adapters.check(steps, kos)) == []
    normal = adapters.resolve(p["normal"], kos, CTX)
    assert {c["data"]["entity_id"] for c in normal} == {
        "switch.plenticore_l_g3_charge_start", "switch.plenticore_l_g3_discharge_start",
        "switch.plenticore_l_g3_block_charge", "switch.plenticore_l_g3_block_discharge"}
    assert all(c["service"] == "turn_off" for c in normal)
    assert adapters.resolve(p["hold"], kos, CTX) == [
        {"domain": "switch", "service": "turn_on", "data": {"entity_id": "switch.plenticore_l_g3_block_discharge"}}]
    charge = adapters.resolve(p["charge"], kos, CTX)
    assert charge[0]["data"] == {"entity_id": "number.plenticore_l_g3_set_charge_rate", "value": 2400}
    assert charge[-1] == {"domain": "switch", "service": "turn_on", "data": {"entity_id": "switch.plenticore_l_g3_charge_start"}}
    export = adapters.resolve(p["export"], kos, CTX)
    assert export[0]["data"] == {"entity_id": "number.plenticore_l_g3_set_discharge_rate", "value": 2400}
    assert export[-1]["data"] == {"entity_id": "switch.plenticore_l_g3_discharge_start"}
    # Inverter Control (grid trimming) and the grid protection are the owner's - never touched
    kos.append("switch.plenticore_l_g3_inverter_control")
    assert all("ems_grid_protection" not in str(c) and "inverter_control" not in str(c)
               for i in steps for c in adapters.resolve(p[i], kos, CTX))


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
    assert adapters.missing(adapters.check(steps, d, optional=p["optional"])) == []
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
                          "select.emma_ess_control_mode"], "hold", "select.batteries_working_mode", "re:maximi[sz]e.?self.?consum"),
        "solaredge_modbus_multi": (["select.solaredge_b1_storage_control_mode", "select.solaredge_b1_storage_command_mode", "select.solaredge_b1_ac_charge_policy",
                                    "number.solaredge_b1_storage_charge_limit", "number.solaredge_b1_storage_command_timeout"],
                                   "charge", "select.solaredge_b1_ac_charge_policy", "Always Allowed"),
        "foxess_modbus": (["select.work_mode", "number.min_soc_on_grid", "number.force_charge_power", "number.force_charge_max_soc"], "charge", "number.force_charge_max_soc", 90),
        "sigen": (["switch.sigen_plant_remote_ems_controlled_by_home_assistant", "select.sigen_plant_remote_ems_control_mode",
                   "number.sigen_plant_ess_max_charging_limit", "number.sigen_plant_ess_max_discharging_limit"], "charge",
                  "number.sigen_plant_ess_max_charging_limit", 2.4),
        "sofar_solax": (["select.sofar_energy_storage_mode", "number.sofar_passive_mode_battery_power_min", "number.sofar_passive_mode_battery_power_max",
                         "button.sofar_passive_mode_battery_charge_discharge"],
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
        assert adapters.missing(adapters.check(steps, ents, p.get("optional"), {"huawei_solar.forcible_charge_soc", "huawei_solar.stop_forcible_charge"})) == [], key
        calls = adapters.resolve(p[intent], ents, ctx)
        got = {c["data"].get("entity_id"): c["data"].get("option", c["data"].get("value")) for c in calls}
        assert got.get(entity) == want, (key, got)
    # emma's control mode is not the battery's working mode
    assert "select.emma_ess_control_mode" not in str(adapters.resolve(adapters.PROFILES["huawei_solar"]["hold"], cases["huawei_solar"][0], ctx))


def test_givenergy_solis_alphaess_from_their_code():
    ctx = {**CTX, "device_id": "dev9", "serial": "AL123"}
    ge = ["select.givenergy_ce123_battery_pause_mode", "number.givenergy_ce123_battery_charge_power_limit",
          "number.givenergy_ce123_battery_discharge_power_limit"]
    p = adapters.PROFILES["givenergy_local"]
    charge = adapters.resolve(p["charge"], ge, ctx)
    svc = [c for c in charge if c["domain"] == "givenergy_local"][0]
    assert svc["service"] == "enable_timed_charge" and svc["data"] == {"device_id": "dev9", "start_time": "11:15", "end_time": "12:30", "charge_target": 90}
    hold = adapters.resolve(p["hold"], ge, ctx)
    assert {"entity_id": "select.givenergy_ce123_battery_pause_mode", "option": "Pause Discharge"} in [c["data"] for c in hold]

    so = ["select.solis_rc_force_charge_discharge", "number.solis_rc_force_battery_charge_power", "number.solis_rc_timeout"]
    p = adapters.PROFILES["solis_modbus"]
    assert adapters.missing(adapters.check({i: p[i] for i in ("normal", "hold", "charge")}, so)) == []
    assert p["reassert_s"] <= 1200  # its remote control times out after 30 min
    charge = adapters.resolve(p["charge"], so, ctx)
    assert [c["data"].get("option", c["data"].get("value")) for c in charge] == ["Solis RC Force Battery Charge", 2400, 30]

    from datetime import datetime

    calls = adapters.resolve(adapters.PROFILES["alphaess"]["charge"], [], {**ctx, **adapters.alpha_windows(datetime(2026, 11, 14, 9, 0))})
    a = next(c for c in calls if c["service"] == "setbatterycharge")
    assert a["service"] == "setbatterycharge" and a["data"]["serial"] == "AL123" and a["data"]["chargestopsoc"] == 90 and a["data"]["enabled"] is True


def test_service_only_profile_is_found_by_its_integration():
    assert adapters.guess_profile(["sensor.alphaess_soc"], {"alphaess"}) == "alphaess"



def test_chargers_from_their_integrations_code():
    easee = adapters.charger_calls("charge", [], "easee", 16, "devE")
    assert easee[0] == {"domain": "easee", "service": "set_charger_dynamic_limit", "data": {"device_id": "devE", "current": 16}}
    assert adapters.charger_calls("stop", [], "easee", 16, "devE")[0]["data"]["action_command"] == "pause"
    circuit = easee[-1]
    assert circuit["service"] == "set_circuit_dynamic_limit"
    assert circuit["data"] == {"device_id": "devE", "current_p1": 16, "current_p2": 16, "current_p3": 16}
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


def test_growatt_frees_the_discharge_rate_like_appdaemon():
    """A free-mode discharge rate left at 0 % (by another system) kept the battery from covering the house."""
    p = adapters.PROFILES["growatt"]
    ents = GROWATT + ["number.growatt_sph_free_mode_discharge_rate", "number.growatt_sph_free_mode_charge_rate",
                      "number.growatt_sph_load_first_stop_charge"]

    def calls(intent):
        return {c["data"]["entity_id"]: (c["service"], c["data"].get("value")) for c in adapters.resolve(p[intent], ents, CTX)}

    normal, hold = calls("normal"), calls("hold")
    assert normal["number.growatt_sph_free_mode_discharge_rate"] == ("set_value", 100)
    assert hold["number.growatt_sph_free_mode_discharge_rate"] == ("set_value", 0)
    assert normal["number.growatt_sph_load_first_stop_charge"] == ("set_value", 100)
    assert normal["switch.growatt_sph_battery_first_slot_1_enabled"][0] == "turn_off"


def test_normal_gives_back_the_limits_a_charge_or_sale_set():
    """A limit set for a grid charge or a sale must not stay: the sun and the house need the full power after."""
    def pats(key, intent):
        return {s[0] for s in adapters.PROFILES[key][intent] if isinstance(s[0], str)}
    assert r"number\..*ess_max_charging_limit$" in pats("sigen", "normal")
    assert r"number\..*ess_maximum_charge_power$" in pats("victron", "normal") & pats("victron", "hold")
    assert r"number\..*max_charge_level$" in pats("ecoflow", "normal") & pats("ecoflow", "hold")
    assert r"number\..*battery_charge_power_limit$" in pats("givenergy_local", "normal")
    assert r"number\..*(grid_first_discharge_rate|discharge_power_rate)$" in pats("growatt_tlxh", "normal")
    assert r"switch\..*solar_sell$" in adapters.PROFILES["deye_esphome"]["restore"]


def test_huawei_givenergy_sungrow_give_full_power_back():
    def pats(key, intent):
        return {x[0] for x in adapters.PROFILES[key][intent] if isinstance(x[0], str)}
    assert r"number\..*maximum_charging_power$" in pats("huawei_solar", "normal") & pats("huawei_solar", "hold")
    assert r"number\..*battery_discharge_power_limit$" in pats("givenergy_local", "normal")
    assert r"number\..*battery_max_discharge_power$" in pats("sungrow", "normal")
    for key in ("huawei_solar", "givenergy_local", "sungrow"):
        for o in adapters.PROFILES[key]["optional"]:
            assert "\\\\" not in o  # a pattern, not a doubled backslash


def test_deye_global_grid_switch_follows_the_setting_programmes_decide():
    from energy_pilot.adapters import PROFILES, resolve

    for key, glob, prog, val in (("solarman", "switch.deye_battery_grid_charging", "select.deye_program_1_charging", "Grid"),
                                 ("deye_esphome", "switch.deye_grid_charge", "switch.deye_time_point_1_charge_enable", None)):
        ents = [glob, prog]
        for intent in ("normal", "hold", "charge", "export"):
            for allowed in (True, False):
                calls = resolve(PROFILES[key][intent], ents, {**CTX, "grid_charge": allowed})
                g = [c for c in calls if c["data"].get("entity_id") == glob]
                assert g and g[0]["service"] == ("turn_on" if allowed else "turn_off"), (key, intent)
        charge = resolve(PROFILES[key]["charge"], ents, {**CTX, "grid_charge": True})
        p = [c for c in charge if c["data"].get("entity_id") == prog][0]
        assert (p["data"].get("option") == val) if val else p["service"] == "turn_on"  # the programme charges


def test_switch_already_set_is_not_sent_again():
    from energy_pilot.control import Controller

    class HA:
        states = {"switch.g": {"state": "on"}, "switch.h": {"state": "unavailable"}}

    c = Controller.__new__(Controller)
    c.ha = HA()
    assert c._matches({"domain": "switch", "service": "turn_on", "data": {"entity_id": "switch.g"}}) is True
    assert c._matches({"domain": "switch", "service": "turn_off", "data": {"entity_id": "switch.g"}}) is False
    assert c._matches({"domain": "switch", "service": "turn_on", "data": {"entity_id": "switch.h"}}) is None


def test_megarevo_through_solarassistant():
    """Megarevo via SolarAssistant: Work mode only - normal and hold, never grid charging; names matched loosely."""
    from energy_pilot import control as C

    mr = ["select.megarevo_work_mode", "select.megarevo_discharge_slot_1_start", "select.megarevo_export_to_grid"]
    assert adapters.guess_profile(mr, {"mqtt"}) == "megarevo"
    p = adapters.PROFILES["megarevo"]
    assert p["grid_charge"] is False
    assert adapters.missing(adapters.check({i: p[i] for i in ("normal", "hold", "charge")}, mr)) == []
    opts = ["Self consume", "Peak shift", "Battery priority"]
    ctl = C.Controller.__new__(C.Controller)
    ctl.ha = type("H", (), {"states": {"select.megarevo_work_mode": {"state": "Self consume", "attributes": {"options": opts}}}})()
    hold = ctl._clamp(adapters.resolve(p["hold"], mr, CTX))
    assert hold[0]["data"] == {"entity_id": "select.megarevo_work_mode", "option": "Battery priority"}
    assert ctl._clamp(adapters.resolve(p["normal"], mr, CTX))[0]["data"]["option"] == "Self consume"
    ctl.ha.states["select.megarevo_work_mode"]["attributes"]["options"] = ["Self Consumption"]
    assert ctl._clamp(adapters.resolve(p["normal"], mr, CTX))[0]["data"]["option"] == "Self Consumption"
    assert ctl._clamp(adapters.resolve(p["hold"], mr, CTX)) == []  # no such option: nothing is sent


def test_victron_is_told_again_every_few_minutes():
    """Victron puts its ESS settings back after about 10 minutes - they are re-sent before that."""
    assert adapters.PROFILES["victron"]["reassert_s"] < 600


def test_select_option_label_or_value_is_matched_to_the_controls_own():
    """A GitHub user's Huawei: the integration has 'maximise_self_consumption', the profile said the label."""
    from types import SimpleNamespace

    from energy_pilot import control as C

    opts = ["adaptive", "fixed_charge_discharge", "maximise_self_consumption", "fully_fed_to_grid", "time_of_use_luna2000"]
    c = C.Controller.__new__(C.Controller)
    c.ha = SimpleNamespace(states={"select.battery_working_mode": {"state": "adaptive", "attributes": {"options": opts}},
                                   "select.inverter_work_mode": {"state": "x", "attributes": {"options": ["Self Use", "Feed-in Priority"]}}})
    steps = adapters.resolve(adapters.PROFILES["huawei_solar"]["normal"], list(c.ha.states), CTX)
    out = c._clamp([s for s in steps if s.get("service") == "select_option"])
    assert out[0]["data"]["option"] == "maximise_self_consumption"
    other = c._clamp([{"domain": "select", "service": "select_option", "data": {"entity_id": "select.inverter_work_mode", "option": "self_use"}}])
    assert other[0]["data"]["option"] == "Self Use"


def test_identifiers_stay_text():
    """A GitHub user's Easee charger has device_id "45" - Easee refuses it as a number."""
    assert adapters.fill({"device_id": "{device_id}", "action_command": "pause"}, {"device_id": "45"}) == \
        {"device_id": "45", "action_command": "pause"}
    assert adapters.fill({"serial": "{serial}"}, {"serial": "123456"}) == {"serial": "123456"}
    assert adapters.fill({"current": "{current}", "target_soc": "{target}"}, {"current": "16", "target": 80}) == \
        {"current": 16, "target_soc": 80}


def test_alphaess_windows_never_overlap_and_carry_power():
    from datetime import datetime

    from energy_pilot import adapters

    w = adapters.alpha_windows(datetime(2026, 11, 14, 11, 22))
    assert {k: v for k, v in w.items() if not k.endswith(("_h", "_m"))} == {"now_from": "10:45", "now_to": "15:15", "now2_from": "00:00", "now2_to": "00:00", "park_c_from": "23:15", "park_c_to": "23:30",
                 "park_d_from": "23:45", "park_d_to": "00:00", "lease_from": "09:15", "lease_to": "12:30"}
    ctx = {"serial": "ALD1", "min_soc": 10, "soc": 43, "target": 80, "power_w": 2500, "max_charge_w": 3000, "max_power_w": 3000, **w}
    prof = adapters.PROFILES["alphaess"]
    for intent in ("normal", "hold", "charge"):
        for svc, _kind, data in prof[intent]:
            d = adapters.fill(data, ctx)
            if svc == "alphaess.setbatterycharge":
                assert d["cp1start"] != d["cp1end"] and d["cp1power"] > 0  # never a deleted (00:00-00:00) period
            else:
                assert d["dp1start"] != d["dp1end"] and d["dp1power"] > 0
    hold = {s: adapters.fill(d, ctx) for s, _k, d in prof["hold"]}
    assert hold["alphaess.setbatterydischarge"]["enabled"] is True and hold["alphaess.setbatterydischarge"]["dp1start"] == "23:45"


def test_alpha_charge_never_over_midnight():
    """AlphaESS: a period that runs over midnight (start after end) never starts - split before and after it."""
    from datetime import datetime

    from energy_pilot.adapters import alpha_windows

    w = alpha_windows(datetime(2026, 11, 14, 22, 33))
    assert (w["now_from"], w["now_to"], w["now2_from"], w["now2_to"]) == ("22:00", "23:45", "00:00", "02:30")
    w = alpha_windows(datetime(2026, 11, 14, 20, 0))
    assert (w["now_from"], w["now_to"]) == ("19:30", "23:45")
    w = alpha_windows(datetime(2026, 11, 14, 12, 10))
    assert (w["now_from"], w["now_to"], w["now2_from"], w["now2_to"]) == ("11:30", "16:00", "00:00", "00:00")


def test_goodwe_profile():
    """GoodWe (Home Assistant's goodwe integration): found by its entities; the eco numbers written before the mode."""
    from energy_pilot import adapters

    ents = ["select.goodwe_inverter_operation_mode", "number.goodwe_eco_mode_power", "number.goodwe_eco_mode_soc",
            "number.goodwe_grid_export_limit", "number.goodwe_battery_discharge_depth"]
    assert adapters.guess_profile(ents, {"goodwe"}) == "goodwe"
    prof = adapters.PROFILES["goodwe"]
    charge = [s[0] for s in prof["charge"]]
    assert charge[-1].startswith("select")  # the mode last
    for opts, intent, want in ((["general", "eco_charge", "eco_discharge"], "charge", "eco_charge"),
                               (["General mode", "Eco charge mode", "Eco discharge mode"], "hold", "Eco discharge mode"),
                               (["General mode", "Eco charge mode"], "normal", "General mode")):
        pat = [v for p, k, v in prof[intent] if k == "select"][0][3:]
        assert adapters.pick_option(pat, opts) == want


def test_goodwe_ems_profile():
    """GoodWe EMS: the operation mode profile is picked by itself when both are there; EMS hits its options."""
    from energy_pilot import adapters

    both = ["select.inverter_operation_mode", "number.goodwe_eco_mode_power", "number.goodwe_eco_mode_soc",
            "select.goodwe_ems_mode", "number.goodwe_ems_power_limit"]
    assert adapters.guess_profile(both, {"goodwe"}) == "goodwe"
    assert adapters.guess_profile(["select.goodwe_ems_mode", "number.goodwe_ems_power_limit"], set()) == "goodwe_ems"
    opts = ["auto", "charge_pv", "discharge_pv", "import_ac", "export_ac", "conserve", "off_grid", "battery_standby",
            "buy_power", "sell_power", "charge_battery", "discharge_battery"]
    prof = adapters.PROFILES["goodwe_ems"]
    for intent, want in (("normal", "auto"), ("hold", "battery_standby"), ("charge", "charge_battery"), ("export", "discharge_battery")):
        pat = [v for p, k, v in prof[intent] if k == "select"][0][3:]
        assert adapters.pick_option(pat, opts) == want
    assert prof["charge"][-1][1] == "select"  # the power limit first, then the mode


def test_hypervolt_full_power_at_the_current_and_stops_by_activation_mode():
    ents = ["select.hypervolt_charge_mode", "number.hypervolt_max_current", "select.hypervolt_activation_mode", "switch.hypervolt_charging"]
    calls = adapters.charger_calls("charge", ents, "hypervolt_charger", 16)
    assert [(c["data"].get("entity_id"), c["data"].get("option", c["data"].get("value"))) for c in calls] == [
        ("select.hypervolt_charge_mode", "Boost"), ("number.hypervolt_max_current", 16), ("select.hypervolt_activation_mode", "Plug and Charge")]
    stop = adapters.charger_calls("stop", ents, "hypervolt_charger", 16)
    assert [(c["data"]["entity_id"], c["data"]["option"]) for c in stop] == [("select.hypervolt_activation_mode", "Schedule Charge")]


def test_predbat_holds():
    """Holds checked against Predbat: Sigenergy self-consumption with discharging at 0 (not "PV First" - a grid
    charge), Powerwall reserve rounded down with grid charging off, Huawei's forcible charge ended by its service."""
    ctx = {**CTX, "soc": 55, "soc_floor": 54, "max_charge_kw": 3.0, "device_id": "d1"}
    sig = ["switch.sigen_plant_remote_ems_controlled_by_home_assistant", "select.sigen_plant_remote_ems_control_mode",
           "number.sigen_plant_ess_max_discharging_limit", "number.sigen_plant_ess_max_charging_limit"]
    got = {c["data"]["entity_id"]: c["data"].get("option", c["data"].get("value")) for c in adapters.resolve(adapters.PROFILES["sigen"]["hold"], sig, ctx)}
    assert got["select.sigen_plant_remote_ems_control_mode"] == "Maximum Self Consumption"
    assert got["number.sigen_plant_ess_max_discharging_limit"] == 0
    tes = ["number.my_home_backup_reserve", "switch.my_home_allow_charging_from_grid", "select.my_home_operation_mode"]
    calls = adapters.resolve(adapters.PROFILES["tesla"]["hold"], tes, ctx)
    assert {"domain": "switch", "service": "turn_off", "data": {"entity_id": "switch.my_home_allow_charging_from_grid"}} in calls
    assert [c for c in calls if c["data"].get("entity_id") == "number.my_home_backup_reserve"][0]["data"]["value"] == 54
    hua = adapters.resolve(adapters.PROFILES["huawei_solar"]["normal"], ["number.batteries_maximum_discharging_power"], ctx)
    assert hua[0] == {"domain": "huawei_solar", "service": "stop_forcible_charge", "data": {"device_id": "d1"}}


def test_predbat_names_found():
    """Victron through HA's own GX integration, Sunsynk with Predbat's entity names, SolarEdge's power control on."""
    gx = ["number.gx_device_ess_max_inverter_power_limit", "number.gx_device_ess_max_charge_power_limit",
          "select.gx_device_ess_mode", "number.gx_device_ac_power_setpoint"]
    assert adapters.guess_profile(gx, {"victron_gx"}) == "victron_ha"
    hold = {c["data"]["entity_id"]: c["data"].get("value", c["data"].get("option")) for c in adapters.resolve(adapters.PROFILES["victron_ha"]["hold"], gx, CTX)}
    assert hold["number.gx_device_ess_max_inverter_power_limit"] == 0
    ss = ["select.sunsynk_prog1_charge_option", "number.sunsynk_set_soc_timezone1", "switch.sunsynk_use_timer"]
    ctx = {**CTX, "hold_soc": 63}
    got = {c["data"]["entity_id"]: c["data"].get("value", c["data"].get("option")) for c in adapters.resolve(adapters.PROFILES["sunsynk"]["charge"], ss, ctx)}
    assert got["number.sunsynk_set_soc_timezone1"] == 90 and got["select.sunsynk_prog1_charge_option"] == "re:^allow grid"
    se = ["switch.solaredge_i1_advanced_power_control", "select.solaredge_i1_storage_control_mode", "number.solaredge_i1_storage_discharge_limit",
          "select.solaredge_i1_storage_command_mode"]
    assert any(c["data"].get("entity_id") == "switch.solaredge_i1_advanced_power_control" for c in adapters.resolve(adapters.PROFILES["solaredge_modbus_multi"]["hold"], se, CTX))
    assert adapters.guess_profile(["select.solax_remotecontrol_power_control", "select.solax_charger_use_mode"], {"solax_modbus"}) != "solax_modbus_rc"


def test_new_brands_from_predbat():
    lux = ["switch.lux_ac_charge_enable", "switch.lux_force_discharge_enable", "number.lux_on_grid_discharge_cut_off_soc",
           "number.lux_ac_battery_charge_level", "time.lux_ac_charge_start1", "time.lux_ac_charge_end1"]
    assert adapters.guess_profile(lux, {"luxpower"}) == "luxpython"
    sol = ["select.solis_inverter_energy_storage_control_switch", "switch.inverter_timed_charge_slot_1_enable",
           "switch.inverter_timed_discharge_slot_1_enable", "number.solis_inverter_timed_charge_soc", "number.solis_inverter_backup_mode_soc"]
    assert adapters.guess_profile(sol, {"solax_modbus"}) == "solis_solax_fb00"
    calls = adapters.resolve(adapters.PROFILES["ep_cube"]["charge"], [], {**CTX})
    assert calls[-1] == {"domain": "ep_cube", "service": "force_charge", "data": {"duration_minutes": 60, "target_pct": 90}}


def test_own_script_step():
    calls = adapters.resolve([("script.fronius_charge", "script", None)], ["script.fronius_charge"], {**CTX})
    assert calls == [{"domain": "script", "service": "turn_on", "data": {"entity_id": "script.fronius_charge",
                      "variables": {"target": 90, "soc": 62, "min_soc": 10, "power_w": 2400, "max_power_w": 3000, "max_charge_w": 3000}}}]


def test_givenergy_without_pause_mode_holds_with_the_discharge_limit():
    """Older GivEnergy firmware has no battery pause mode (#92): the discharge limit at 0 W holds instead."""
    p = adapters.PROFILES["givenergy_local"]
    ge = ["number.givenergy_ce123_battery_charge_power_limit", "number.givenergy_ce123_battery_discharge_power_limit"]
    assert adapters.missing(adapters.check({i: p[i] for i in ("normal", "hold", "charge", "export")}, ge, p["optional"])) == []
    ctx = {**CTX, "device_id": "dev9"}
    lim = lambda intent: {c["data"]["entity_id"]: c["data"]["value"] for c in adapters.resolve(p[intent], ge, ctx)
                          if c["data"].get("entity_id", "").endswith("discharge_power_limit")}
    assert lim("hold") == {"number.givenergy_ce123_battery_discharge_power_limit": 0}
    assert lim("normal")["number.givenergy_ce123_battery_discharge_power_limit"] > 0
    assert lim("export")["number.givenergy_ce123_battery_discharge_power_limit"] > 0
    # without the discharge limit it isn't controlled at all - never half a hold
    assert adapters.missing(adapters.check({i: p[i] for i in ("normal", "hold", "charge")}, ge[:1], p["optional"]))


def test_sofar_me3000_zcs_through_solarman():
    # ZCS Azzurro 3000SP = Sofar ME 3000-SP (davidrapan's sofar_hybrid): Work Mode and one timed window, no passive power.
    ents = ["select.zcs_work_mode", "time.zcs_timed_charge_start", "time.zcs_timed_charge_end", "time.zcs_timed_discharge_start",
            "time.zcs_timed_discharge_end", "number.zcs_timed_charge_power", "number.zcs_timed_discharge_power"]
    assert adapters.guess_profile(ents, {"solarman"}, "sofar_hybrid") == "sofar_me"
    p = adapters.PROFILES["sofar_me"]
    ctx = {**CTX, "now_from": "02:00", "now_to": "05:00"}
    charge = {c["data"]["entity_id"]: c["data"] for c in adapters.resolve(p["charge"], ents, ctx)}
    assert charge["number.zcs_timed_charge_power"]["value"] == 2400
    assert charge["time.zcs_timed_charge_start"]["time"] == "02:00:00" and charge["time.zcs_timed_charge_end"]["time"] == "05:00:00"
    assert charge["select.zcs_work_mode"]["option"] == "Timed"
    order = [c["data"]["entity_id"] for c in adapters.resolve(p["charge"], ents, ctx)]
    assert order[-1] == "select.zcs_work_mode" and order.index("time.zcs_timed_charge_end") < order.index("number.zcs_timed_charge_power")
    assert charge["number.zcs_timed_discharge_power"]["value"] == 0
    hold = {c["data"]["entity_id"]: c["data"] for c in adapters.resolve(p["hold"], ents, ctx)}
    assert hold["number.zcs_timed_discharge_power"]["value"] == 0 and hold["time.zcs_timed_charge_end"]["time"] == "00:00:00"
    assert adapters.resolve(p["normal"], ents, ctx)[0]["data"]["option"] == "Auto"



def test_sigenergy_without_its_discharge_limit_says_so():
    """The discharge limit is off by default in the integration - without it "hold" can't stop the battery."""
    p = adapters.PROFILES["sigen"]
    ents = ["switch.sigen_plant_remote_ems_controlled_by_home_assistant", "select.sigen_plant_remote_ems_control_mode",
            "number.sigen_plant_ess_max_charging_limit"]
    assert adapters.missing(adapters.check({i: p[i] for i in ("normal", "hold", "charge")}, ents, p.get("optional"))) \
        == [r"number\..*ess_max_discharging_limit$"] * 2



def test_sofar_solax_sends_the_passive_values_with_its_button():
    """SolaX Modbus keeps the passive numbers until "Passive: Update Battery Charge/Discharge" writes them (0x1187)."""
    p = adapters.PROFILES["sofar_solax"]
    ents = ["select.sofar_energy_storage_mode", "number.sofar_passive_mode_battery_power_min",
            "number.sofar_passive_mode_battery_power_max", "button.sofar_passive_mode_battery_charge_discharge"]
    for intent in ("hold", "charge"):
        calls = adapters.resolve(p[intent], ents, {"power_w": 2000, "max_charge_w": 3000})
        assert calls[-1] == {"domain": "button", "service": "press", "data": {"entity_id": "button.sofar_passive_mode_battery_charge_discharge"}}


def test_audit_fixes_names_and_values():
    """Found in the integrations' own code (28 November): translated ids, the right option, text where text is wanted."""
    e3 = adapters.resolve(adapters.PROFILES["e3dc_rscp"]["hold"], [], {"device_id": "d"})
    assert e3[0]["data"]["power_mode"] == "1"  # a string: E3DC refuses a number
    opts = ["Self-Use - No Grid Charging", "Backup/Reserve - No Grid Charging", "Backup/Reserve", "Off-Grid Mode"]
    want = adapters.PROFILES["solis_solax_fb00"]["charge"][0][2][3:]
    assert adapters.pick_option(want, opts) == "Backup/Reserve"
    assert adapters.pick_option("^stop$||force.?charge", ["Self-consumption", "Force charge", "Stop"]) == "Stop"
    assert adapters.pick_option("^stop$||force.?charge", ["Self-consumption", "Force charge"]) == "Force charge"
    hu = adapters.PROFILES["huawei_solar"]
    assert any(adapters.hit(st[0], "switch.tk_storage_charge_from_grid_function") for st in hu["charge"])
    assert any(adapters.hit(st[0], "number.tk_backup_reserve_percent") for st in adapters.PROFILES["tesla"]["hold"])
    assert any(adapters.hit(st[0], "time.lux_ab12345678_ac_charge_start1") for st in adapters.PROFILES["luxpython"]["charge"])
    give = [st for st in adapters.PROFILES["givenergy_local"]["export"] if "discharge_power_limit" in st[0]]
    assert give[0][2] == "{power_w}"  # the planned power, not full power

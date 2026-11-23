"""Found in users' setups: translated entity ids, a door lock as the house battery, Kostal's solar as the car's power."""

from energy_pilot import adapters
from energy_pilot.detect import fits_role


def test_swedish_wallbox_found_by_its_integration_key():
    ents = ["number.wallbox_maximal_laddningsstrom", "switch.wallbox_pausa_ateruppta"]
    adapters.ALIASES = {ents[0]: adapters.alias_for(ents[0], "maximum_charging_current"),
                        ents[1]: adapters.alias_for(ents[1], "pause_resume")}
    try:
        calls = adapters.charger_calls("charge", ents, "wallbox", 16)
        assert {c["data"]["entity_id"] for c in calls} == set(ents)
        assert adapters.charger_calls("stop", ents, "wallbox", 16)[0]["data"]["entity_id"] == ents[1]
    finally:
        adapters.ALIASES = {}


def test_roles_that_cannot_be():
    w, pct, kwh = {"unit_of_measurement": "W"}, {"unit_of_measurement": "%"}, {"unit_of_measurement": "kWh"}
    assert not fits_role("battery_soc", "sensor.front_door_lock_battery_level", pct, "zwave_js")
    assert not fits_role("battery_power", "sensor.fire_10_hd_battery_power", w, None)
    assert fits_role("battery_soc", "sensor.foxess_battery_soc", pct, "foxess_modbus")
    assert not fits_role("ev_power", "sensor.hostname_scb_5313dd_solar_power", w, "kostal_plenticore")
    assert not fits_role("ev_power", "sensor.garage_monta_opladningsenergi", kwh, "monta")
    assert fits_role("ev_power", "sensor.easee_power", {"unit_of_measurement": "kW"}, "easee")
    assert not fits_role("sell_price", "sensor.grid_power_export", w, None)
    assert fits_role("sell_price", "sensor.feed_in_rate", {"unit_of_measurement": "€/kWh"}, None)


def test_grid_sensors_are_no_house():
    w = {"unit_of_measurement": "W"}
    for e in ("sensor.foxess_grid_consumption_power_2", "sensor.grid_to_house", "sensor.x_current_net_power_consumption"):
        assert not fits_role("house_power", e, w, None), e
    for e in ("sensor.foxess_load_power", "sensor.hausverbrauch_gesamt_errechnet_aus_modbus", "sensor.house_consumption"):
        assert fits_role("house_power", e, w, None), e


def test_more_batteries_that_are_no_house_battery():
    pct, w = {"unit_of_measurement": "%"}, {"unit_of_measurement": "W"}
    assert not fits_role("battery_soc", "sensor.hallway_battery_level", pct, "hive")
    assert not fits_role("battery_soc", "sensor.buiten_vsszzzaazld501076_battery_level", pct, "get_euda_data")
    assert not fits_role("battery_soc", "sensor.garage_wvwzzzaazld501076_battery_level", pct, None)  # a VIN, any platform
    assert not fits_role("battery_soc", "sensor.home_energy_meter_battery_level", pct, None)
    assert not fits_role("battery_soc", "sensor.garden_soil_battery", pct, None)
    for ok in ("sensor.meterkast_gx_device_dc_battery_charge", "sensor.sigen_plant_battery_state_of_charge",
               "sensor.battery_level", "sensor.foxess_bat_soc", "sensor.sd2236g476_battery_soc"):
        assert fits_role("battery_soc", ok, pct, None), ok
    assert fits_role("battery_power", "sensor.edge_meter_bess_kw", w, "template")


def test_an_ebike_or_a_mower_is_no_car_charger():
    from energy_pilot.chargers import NOT_CHARGER, find
    from energy_pilot.detect import NOT_EV_POWER

    for e in ("sensor.garage_e_bike_charger_power", "sensor.bicycle_charger_power", "sensor.tuin_fiets_lader_stroom",
              "sensor.automower_power", "sensor.elcykel_lader_effekt", "sensor.plaeneklipper_power"):
        assert NOT_EV_POWER.search(e), e
    for e in ("sensor.easee_power", "sensor.zappi_power", "sensor.wallbox_laddningseffekt", "sensor.go_echarger_power",
              "sensor.ohme_power_draw", "sensor.laadpaal_vermogen", "sensor.velux_window"):
        assert not NOT_EV_POWER.search(e), e
    assert NOT_CHARGER.search("mower") and not NOT_CHARGER.search("easee_charger_enabled")
    w = {"unit_of_measurement": "W"}
    st = {"sensor.ebike_charging_power": {"state": "90", "attributes": w}, "binary_sensor.ebike_charging_plug": {"state": "on", "attributes": {}}}
    assert find(st, None, None, [], []) == []  # a bike with a plug sensor is not offered as another charger


def test_one_parts_meter_is_not_anothers():
    w = {"unit_of_measurement": "W"}
    for role, e in (("battery_power", "sensor.lxp_generator_power"), ("battery_power", "sensor.foxess_pv1_power_2"),
                    ("pv_power", "sensor.lxp_energy_flow"), ("pv_power", "sensor.myenergi_home_libbi_power_grid"),
                    ("grid_power", "sensor.goodwe_homekit_load"), ("grid_power", "sensor.power_battery_charge_grid_pees"),
                    ("house_power", "sensor.solar_to_house"), ("house_power", "sensor.total_battery_demand_out_w")):
        assert not fits_role(role, e, w, None), e
    for role, e in (("house_power", "sensor.omnibattery_home_consumption"), ("battery_power", "sensor.solarflow_800_plus_output_pack_power"),
                    ("pv_power", "sensor.solarflow_800_plus_solar_input_power"), ("pv_power", "sensor.foxess_pv1_power"),
                    ("grid_power", "sensor.pvhub_grid_meter_power_net_power"), ("battery_power", "sensor.foxess_battery_charge"),
                    ("grid_power", "sensor.growatt_grid_power"), ("pv_power", "sensor.deye_pv_power")):
        assert fits_role(role, e, w, None), e

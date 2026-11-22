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

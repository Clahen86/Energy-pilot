"""Deye/Sunsynk through the Sunsynk add-on (ss_prog1_capacity ...), and HA's "_2" entity ids."""
from energy_pilot import adapters

ENTS = ["number.deye_inverter_battery_low_capacity", "select.deye_inverter_battery_type", "switch.ss_use_timer",
        "switch.ss_grid_charge_enabled", "switch.ss_priority_load", "switch.ss_solar_export", "select.ss_load_limit"] + \
    [f"number.ss_prog{n}_capacity" for n in range(1, 7)] + [f"number.ss_prog{n}_power" for n in range(1, 7)] + \
    [f"select.ss_prog{n}_charge" for n in range(1, 7)] + [f"select.ss_prog{n}_time" for n in range(1, 7)]


def test_sunsynk_addon_gets_its_own_profile_not_solarman():
    assert adapters.guess_profile(ENTS, {"mqtt"}, "12kW Inverter (**2066) deye_inverter") == "sunsynk"
    assert adapters.guess_profile(ENTS, set()) == "sunsynk"


def test_second_entity_suffix_still_found():
    assert adapters.hit(r"select\..*rc_force_charge_discharge$", "select.rc_force_charge_discharge_2")
    assert not adapters.hit(r"select\..*rc_force_charge_discharge$", "select.rc_force_charge_discharge_mode")

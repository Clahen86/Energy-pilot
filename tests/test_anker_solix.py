"""Anker SOLIX Solarbank through thomluther/ha-anker-solix: names and options from its source (3.9.2)."""

from energy_pilot import adapters as A

ENTS = ["select.solarbank_4_e5000_pro_usage_mode", "number.solarbank_4_e5000_pro_system_load_preset",
        "number.solarbank_4_e5000_pro_soc_min", "sensor.solarbank_4_e5000_pro_state_of_charge"]
CTX = {"power_w": 1200, "target": 90}


def steps(intent):
    return [(c["data"]["entity_id"], c["data"].get("option", c["data"].get("value"))) for c in A.resolve(A.PROFILES["anker_solix"][intent], ENTS, CTX)]


def test_anker_solix_found_and_steps():
    assert A.guess_profile(ENTS, {"anker_solix"}) == "anker_solix"
    assert steps("charge") == [(ENTS[0], "backup")]
    assert steps("hold") == [(ENTS[0], "manual"), (ENTS[1], 0)]
    assert steps("export") == [(ENTS[0], "manual"), (ENTS[1], 1200)]
    assert steps("normal") == [(ENTS[0], "re:^smart(meter)?$")]  # the option picked from the select's own list
    assert A.pick_option("^smart(meter)?$", ["manual", "smartmeter", "backup"]) == "smartmeter"
    assert A.pick_option("^smart(meter)?$", ["manual", "smartplugs", "backup"]) is None  # no meter: not taken for plugs

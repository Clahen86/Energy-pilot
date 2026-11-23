"""GivEnergy through GivTCP (MQTT): entity names and options from GivTCP's source (3.6.14)."""

from energy_pilot import adapters as A

SN = "ce1234g567"
ENTS = [f"select.givtcp_{SN}_mode", f"select.givtcp_{SN}_battery_pause_mode", f"select.givtcp_{SN}_force_charge",
        f"number.givtcp_{SN}_target_soc", f"number.givtcp_{SN}_charge_target_soc_1",
        f"select.givtcp_{SN}_charge_start_time_slot_1", f"select.givtcp_{SN}_charge_end_time_slot_1",
        f"select.givtcp_{SN}_discharge_start_time_slot_1", f"select.givtcp_{SN}_discharge_end_time_slot_1",
        f"switch.givtcp_{SN}_enable_charge_schedule", f"switch.givtcp_{SN}_enable_discharge_schedule",
        f"number.givtcp_{SN}_battery_charge_rate", f"number.givtcp_{SN}_battery_discharge_rate",
        f"number.givtcp_{SN}_battery_charge_rate_ac", f"sensor.givtcp_{SN}_soc"]
CTX = {"target": 90, "power_w": 2500, "max_charge_w": 3600, "max_power_w": 3600, "lease_from": "01:30", "lease_to": "04:45", "soc": 50, "min_soc": 10}


def calls(intent):
    return {c["data"]["entity_id"].split(SN + "_")[1]: c["data"].get("option", c["data"].get("value", c["service"]))
            for c in A.resolve(A.PROFILES["givtcp"][intent], ENTS, CTX)}


def test_givtcp_is_found_not_givenergy_local():
    assert A.guess_profile(ENTS, {"mqtt"}) == "givtcp"
    assert A.guess_profile(["select.givenergy_ce1234_battery_pause_mode", "number.givenergy_ce1234_battery_charge_power_limit",
                            "number.givenergy_ce1234_battery_discharge_power_limit"], {"givenergy_local"}) == "givenergy_local"


def test_givtcp_steps():
    c = calls("charge")
    assert c["mode"] == "Eco" and c["target_soc"] == 90 and c["charge_target_soc_1"] == 90
    assert c["charge_start_time_slot_1"] == "01:30:00" and c["charge_end_time_slot_1"] == "04:45:00"
    assert c["battery_charge_rate"] == 2500 and c["enable_charge_schedule"] == "turn_on"
    assert "battery_pause_mode" not in c and "battery_charge_rate_ac" not in c and "force_charge" not in c
    h = calls("hold")
    assert h["battery_discharge_rate"] == 0 and h["enable_charge_schedule"] == "turn_off"
    n = calls("normal")
    assert n["mode"] == "Eco" and n["battery_discharge_rate"] == 3600
    e = calls("export")
    assert e["mode"] == "Timed Export" and e["discharge_start_time_slot_1"] == "01:30:00" and e["enable_discharge_schedule"] == "turn_on"

"""SolaX read through its own (local) integration and steered through SolaX Modbus on a device of its own (#56): the
Modbus controls are found, not "7 controls missing"."""

import asyncio

from energy_pilot.control import Controller


class HA:
    def __init__(self, states, reg):
        self.states, self.reg, self.config = states, reg, {}

    async def command(self, msg):
        if msg["type"] == "config/entity_registry/list":
            return self.reg
        if msg["type"] == "config/device_registry/list":
            return [{"id": "g4", "model": "x1_hybrid_gen4"}, {"id": "mb", "name": "SolaX Inverter"}]
        if msg["type"] == "get_services":
            return {}
        return []


class OV:
    def __init__(self, roles, settings):
        self.r, self.settings = roles, settings

    def role(self, k):
        return self.r.get(k)


REG = [{"entity_id": "sensor.solax_snkbgylxt7_battery_soc", "platform": "solax", "device_id": "g4"},
       {"entity_id": "select.buanderie_solax_inverter_charger_use_mode", "platform": "solax_modbus", "device_id": "mb"},
       {"entity_id": "select.buanderie_solax_inverter_manual_mode_select", "platform": "solax_modbus", "device_id": "mb"},
       {"entity_id": "switch.poele_prise_1", "platform": "tuya", "device_id": "x"}]


def _run(settings):
    c = Controller(HA({e["entity_id"]: {"state": "1"} for e in REG}, REG),
                   OV({"battery_soc": "sensor.solax_snkbgylxt7_battery_soc"}, settings), None)
    asyncio.run(c.discover())
    return c


def test_controls_from_the_chosen_profiles_integration():
    c = _run({"inverter_profile": "solax_modbus"})
    assert c.entities["battery"] == ["select.buanderie_solax_inverter_charger_use_mode",
                                     "select.buanderie_solax_inverter_manual_mode_select"]
    assert c.platforms["battery"] == "solax_modbus"


def test_found_without_a_chosen_profile_too():
    c = _run({})
    assert "select.buanderie_solax_inverter_manual_mode_select" in c.entities["battery"]
    assert c.profile_key() == "solax_modbus"


class OVS(OV):
    def save(self, changes, source=None):
        self.settings.update(changes)
        self.saved = (changes, source)


def test_wrong_profile_chosen_by_hand_is_mended():
    """Fox ESS Modbus with "Fox ESS (cloud)" chosen: its controls are never found - the Modbus profile is taken."""
    reg = [{"entity_id": "sensor.battery_soc", "platform": "foxess_modbus", "device_id": "fox"},
           {"entity_id": "select.work_mode", "platform": "foxess_modbus", "device_id": "fox"},
           {"entity_id": "number.force_charge_power", "platform": "foxess_modbus", "device_id": "fox"},
           {"entity_id": "number.force_discharge_power", "platform": "foxess_modbus", "device_id": "fox"},
           {"entity_id": "number.min_soc_on_grid", "platform": "foxess_modbus", "device_id": "fox"},
           {"entity_id": "number.max_soc", "platform": "foxess_modbus", "device_id": "fox"}]
    ov = OVS({"battery_soc": "sensor.battery_soc"}, {"inverter_profile": "foxess"})
    c = Controller(HA({e["entity_id"]: {"state": "1"} for e in reg}, reg), ov, None)
    asyncio.run(c.discover())
    assert ov.settings["inverter_profile"] == "foxess_modbus" and ov.saved[1] == "energy_pilot"


def test_a_profile_that_finds_its_controls_is_kept():
    ov = OVS({"battery_soc": "sensor.solax_snkbgylxt7_battery_soc"}, {"inverter_profile": "solax_modbus"})
    c = Controller(HA({e["entity_id"]: {"state": "1"} for e in REG}, REG), ov, None)
    asyncio.run(c.discover())
    assert ov.settings["inverter_profile"] == "solax_modbus" and not hasattr(ov, "saved")

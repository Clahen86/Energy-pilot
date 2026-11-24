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

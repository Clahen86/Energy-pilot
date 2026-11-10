"""A charger behind a sum sensor (Zappi + "All EV power" group): its own device is found from the plug, never other
group switches - and a battery's minimum-level setting is not an extra battery."""

import asyncio

from energy_pilot import batteries
from energy_pilot.control import Controller


class HA:
    def __init__(self, states, reg):
        self.states, self.reg, self.config = states, reg, {}

    async def command(self, msg):
        if msg["type"] == "config/entity_registry/list":
            return self.reg
        if msg["type"] == "config/device_registry/list":
            return [{"id": "zappi", "model": "zappi"}]
        if msg["type"] == "get_services":
            return {}
        return []


class OV:
    settings: dict = {}

    def __init__(self, roles):
        self.r = roles

    def role(self, k):
        return self.r.get(k)


def test_zappi_behind_a_group_sensor():
    reg = [{"entity_id": "sensor.all_ev_power", "platform": "group"},
           {"entity_id": "switch.all_non_dimmable_internal_lights", "platform": "group"},
           {"entity_id": "switch.all_switches_excluding_lights", "platform": "group"},
           {"entity_id": "sensor.myenergi_zappi_plug_status", "platform": "myenergi", "device_id": "zappi"},
           {"entity_id": "select.myenergi_zappi_charge_mode", "platform": "myenergi", "device_id": "zappi"},
           {"entity_id": "sensor.gx_device_dc_battery_charge", "platform": "victron"}]
    states = {e["entity_id"]: {"state": "1"} for e in reg}
    c = Controller(HA(states, reg), OV({"ev_power": "sensor.all_ev_power", "ev_plug": "sensor.myenergi_zappi_plug_status",
                                        "battery_soc": "sensor.gx_device_dc_battery_charge"}), None)
    asyncio.run(c.discover())
    assert c.entities["car"] == ["select.myenergi_zappi_charge_mode"] and c.platforms["car"] == "myenergi"


def test_minimum_soc_setting_is_not_a_battery():
    st = {"sensor.home_minimum_state_of_charge": {"state": "50", "attributes": {"unit_of_measurement": "%", "friendly_name": "Home Minimum State of Charge"}},
          "sensor.gx_device_dc_battery_charge": {"state": "91", "attributes": {"unit_of_measurement": "%", "device_class": "battery"}}}
    assert batteries.find(st, "sensor.gx_device_dc_battery_charge", [], []) == []

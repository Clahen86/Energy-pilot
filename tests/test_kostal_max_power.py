"""A Kostal's "Battery Max Control Power" (W, worked out by Kostal Plenticore Battery Control): the battery's power when
none is set, and the cap on what is set - a value typed in watts (11599.9 "kW") no longer plans with 11.6 MW."""

import asyncio

from energy_pilot.batteries import main_kw
from energy_pilot.control import Controller


class HA:
    def __init__(self, states, reg):
        self.states, self.reg, self.config = states, reg, {}

    async def command(self, msg):
        if msg["type"] == "config/entity_registry/list":
            return self.reg
        if msg["type"] == "config/device_registry/list":
            return [{"id": "g3", "model": "PLENTICORE L G3"}, {"id": "plus", "model": "PLENTICORE plus"}]
        if msg["type"] == "get_services":
            return {}
        return []


class OV:
    settings: dict = {}

    def role(self, k):
        return {"battery_soc": "sensor.plenticore_l_g3_battery_soc"}.get(k)


G3 = ["sensor.plenticore_l_g3_battery_soc", "switch.plenticore_l_g3_charge_start", "switch.plenticore_l_g3_discharge_start",
      "switch.plenticore_l_g3_block_charge", "switch.plenticore_l_g3_block_discharge",
      "number.plenticore_l_g3_set_charge_rate", "number.plenticore_l_g3_set_discharge_rate",
      "sensor.plenticore_l_g3_battery_max_control_power", "number.plenticore_l_g3_house_fuse_size"]


def _ctl(watts):
    reg = [{"entity_id": e, "platform": "kostal_modbus_control", "device_id": "g3"} for e in G3]
    states = {e: {"state": "off"} for e in G3}
    states["sensor.plenticore_l_g3_battery_max_control_power"] = {"state": watts, "attributes": {"unit_of_measurement": "W"}}
    states["number.plenticore_l_g3_house_fuse_size"] = {"state": "50.0"}
    reg.append({"entity_id": "number.plenticore_a_plus_house_fuse_size", "platform": "kostal_modbus_control", "device_id": "plus"})
    states["number.plenticore_a_plus_house_fuse_size"] = {"state": "25.0"}
    # The Plenticore Plus on the same integration (no battery, sorts first): its 6999 W is never taken for the G3's.
    reg.append({"entity_id": "sensor.plenticore_a_plus_battery_max_control_power", "platform": "kostal_modbus_control", "device_id": "plus"})
    states["sensor.plenticore_a_plus_battery_max_control_power"] = {"state": "6999", "attributes": {"unit_of_measurement": "W"}}
    c = Controller(HA(states, reg), OV(), None)
    asyncio.run(c.discover())
    return c


def test_reads_the_g3s_max_power_in_kw():
    assert _ctl("11850").max_power_kw() == 11.85
    assert _ctl("unavailable").max_power_kw() is None


def test_max_power_sets_and_caps_the_battery_power():
    assert main_kw({}, 11.85) == (11.85, 11.85)  # nothing set: what the inverter can
    assert main_kw({"battery_charge_kw": 11599.9}, 11.85) == (11.85, 11.85)  # watts typed as kW: capped
    assert main_kw({"battery_charge_kw": 6, "battery_discharge_kw": 8}, 11.85) == (6, 8)  # the user's own, lower: kept
    assert main_kw({}, None) == (3, 3)  # no sensor: as before
    assert main_kw({"battery_charge_kw": 5}, None) == (5, 5)


def test_reads_the_g3s_fuse_size():
    assert _ctl("11850").fuse_amps() == 50.0  # not the Plus' 25 A

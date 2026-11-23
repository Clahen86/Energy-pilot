"""A Kostal asleep at night ("Off") first starts up and checks the grid before it charges: the self-test waits for its
inverter state to say FeedIn (6) before it judges."""

import asyncio

from energy_pilot.control import Controller


class HA:
    def __init__(self, states, reg):
        self.states, self.reg, self.config = states, reg, {}

    async def command(self, msg):
        if msg["type"] == "config/entity_registry/list":
            return self.reg
        if msg["type"] == "config/device_registry/list":
            return [{"id": "g3", "model": "PLENTICORE L G3"}]
        if msg["type"] == "get_services":
            return {}
        return []


class OV:
    settings: dict = {}

    def role(self, k):
        return {"battery_soc": "sensor.plenticore_l_g3_battery_soc"}.get(k)


def _ctl(state):
    names = ["sensor.plenticore_l_g3_battery_soc", "sensor.plenticore_l_g3_inverter_state",
             "switch.plenticore_l_g3_charge_start", "switch.plenticore_l_g3_discharge_start",
             "switch.plenticore_l_g3_block_charge", "switch.plenticore_l_g3_block_discharge",
             "number.plenticore_l_g3_set_charge_rate", "number.plenticore_l_g3_set_discharge_rate"]
    reg = [{"entity_id": e, "platform": "kostal_modbus_control", "device_id": "g3"} for e in names]
    states = {e: {"state": "off"} for e in names}
    states["sensor.plenticore_l_g3_inverter_state"] = {"state": state}
    # another inverter's state on another device is never taken for the G3's
    states["sensor.other_inverter_state"] = {"state": "6"}
    reg.append({"entity_id": "sensor.other_inverter_state", "platform": "other", "device_id": "x"})
    c = Controller(HA(states, reg), OV(), None)
    asyncio.run(c.discover())
    return c


def test_two_kostals_on_one_integration_use_the_soc_sensors_own():
    """A Plenticore Plus (sorts first: "plenticore_a…") next to the G3: the G3's switches are used, not the other's."""
    g3 = ["sensor.plenticore_l_g3_battery_soc", "switch.plenticore_l_g3_charge_start", "switch.plenticore_l_g3_block_discharge",
          "switch.plenticore_l_g3_discharge_start", "switch.plenticore_l_g3_block_charge", "number.plenticore_l_g3_set_charge_rate"]
    other = ["switch.plenticore_a_plus_charge_start", "switch.plenticore_a_plus_block_discharge",
             "switch.plenticore_a_plus_discharge_start", "switch.plenticore_a_plus_block_charge", "number.plenticore_a_plus_set_charge_rate"]
    reg = [{"entity_id": e, "platform": "kostal_modbus_control", "device_id": "g3"} for e in g3]
    reg += [{"entity_id": e, "platform": "kostal_modbus_control", "device_id": "plus"} for e in other]
    c = Controller(HA({e: {"state": "off"} for e in g3 + other}, reg), OV(), None)
    asyncio.run(c.discover())
    calls = c.calls("battery", {"intent": "hold", "ctx": {}})
    assert [x["data"]["entity_id"] for x in calls] == ["switch.plenticore_l_g3_block_discharge"]
    charge = c.calls("battery", {"intent": "charge", "ctx": {"power_w": 2000}})
    assert {x["data"]["entity_id"] for x in charge} == {"number.plenticore_l_g3_set_charge_rate", "switch.plenticore_l_g3_charge_start"}


def test_kostal_waits_for_feed_in():
    assert _ctl("0").profile_key() == "kostal_modbus_control"
    assert _ctl("0").ready() is False  # Off
    assert _ctl("4").ready() is False  # StartUp
    assert _ctl("6").ready() is True  # FeedIn
    assert _ctl("unavailable").ready() is None  # nothing to tell by: the test does not wait

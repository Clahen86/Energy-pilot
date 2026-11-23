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


def test_kostal_waits_for_feed_in():
    assert _ctl("0").profile_key() == "kostal_modbus_control"
    assert _ctl("0").ready() is False  # Off
    assert _ctl("4").ready() is False  # StartUp
    assert _ctl("6").ready() is True  # FeedIn
    assert _ctl("unavailable").ready() is None  # nothing to tell by: the test does not wait

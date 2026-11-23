"""A Kostal's own minimum and maximum SoC limit (Kostal Plenticore Battery Control's numbers): the inverter won't take
the battery past them, so the plan stays inside them too."""

import asyncio
from datetime import datetime, timedelta

from energy_pilot.control import Controller
from energy_pilot.engine import Battery, Hour, inverter_limits, plan_battery


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
      "number.plenticore_l_g3_battery_minimum_soc_limit", "number.plenticore_l_g3_battery_maximum_soc_limit"]


def _ctl(low, high, other=False):
    reg = [{"entity_id": e, "platform": "kostal_modbus_control", "device_id": "g3"} for e in G3]
    states = {e: {"state": "off"} for e in G3}
    states["number.plenticore_l_g3_battery_minimum_soc_limit"] = {"state": low}
    states["number.plenticore_l_g3_battery_maximum_soc_limit"] = {"state": high}
    if other:
        # A Plenticore Plus on the same integration (sorts first) with limits of its own: never taken for the G3's.
        for e, v in (("number.plenticore_a_plus_battery_minimum_soc_limit", "60"), ("number.plenticore_a_plus_battery_maximum_soc_limit", "70")):
            reg.append({"entity_id": e, "platform": "kostal_modbus_control", "device_id": "plus"})
            states[e] = {"state": v}
    c = Controller(HA(states, reg), OV(), None)
    asyncio.run(c.discover())
    return c


def test_reads_the_kostal_limits():
    assert _ctl("20.0", "80.0").soc_limits() == (20.0, 80.0)
    assert _ctl("5.0", "100.0").soc_limits() == (5.0, 100.0)  # not in use
    assert _ctl("unavailable", "unknown").soc_limits() == (None, None)


def test_the_g3s_own_limits_with_two_inverters():
    assert _ctl("20.0", "80.0", other=True).soc_limits() == (20.0, 80.0)


def test_limits_narrow_the_plan_only():
    assert inverter_limits(10, 95, 20, 80) == (20, 80, 80)  # both in use
    assert inverter_limits(10, 95, 5, 100) == (10, 100, 95)  # not in use: nothing changes
    assert inverter_limits(30, 95, 20, None) == (30, 100, 95)  # the user's own minimum is higher: it stays
    assert inverter_limits(10, 95, None, None) == (10, 100, 95)
    assert inverter_limits(40, 95, None, 30) == (40, 100, 95)  # a maximum below the minimum: a slip, ignored


def test_the_plan_never_charges_past_the_maximum():
    start = datetime(2026, 11, 23)
    # Cheap at night, dear in the evening: the plan wants it full - but the inverter stops at 60 %.
    hours = [Hour(start + timedelta(hours=i), 0.5 if i < 6 else 4.0, 0.0, 1.0, 0.0) for i in range(24)]
    p = plan_battery(hours, 20, Battery(capacity_kwh=10, max_charge_kw=5, max_discharge_kw=5, min_soc=20, max_soc=60, grid_max_soc=60))
    assert max(s.soc_end for s in p.steps) <= 60
    assert min(s.soc_end for s in p.steps) >= 20

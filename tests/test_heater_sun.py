"""A water heater with a temperature of its own heats 10 °C extra on sun that would be sold cheaply, and goes back."""
import asyncio
from datetime import datetime, timedelta

from energy_pilot.things import Things


class HA:
    def __init__(self):
        self.states = {"water_heater.vvb": {"state": "eco", "attributes": {"temperature": 55, "max_temp": 70}}}
        self.calls = []

    async def call_service(self, d, s, data):
        self.calls.append((d, s, data))
        if d == "water_heater":
            self.states["water_heater.vvb"]["attributes"]["temperature"] = data["temperature"]


def test_sun_boost_and_back(tmp_path):
    th = Things({})
    t = {"id": "h1", "kind": "heater", "temp": "water_heater.vvb"}
    ha, t0 = HA(), datetime(2026, 6, 1, 12, 0)
    for i in range(12):  # 6 minutes selling 2 kW at 0.1 while buying costs 2.0
        asyncio.run(th._sun_boost(ha, t, t0 + timedelta(seconds=30 * i), 2.0, 0.1, -2000, True))
    assert ha.calls[-1] == ("water_heater", "set_temperature", {"entity_id": "water_heater.vvb", "temperature": 65})
    for i in range(12):  # the sun gone: buying again
        asyncio.run(th._sun_boost(ha, t, t0 + timedelta(minutes=10, seconds=30 * i), 2.0, 0.1, 500, True))
    assert ha.calls[-1][2]["temperature"] == 55 and len(ha.calls) == 2


def test_no_boost_when_selling_pays():
    import tempfile

    th = Things({})
    ha, t0 = HA(), datetime(2026, 6, 1, 12, 0)
    for i in range(12):
        asyncio.run(th._sun_boost(ha, {"id": "h1", "kind": "heater", "temp": "water_heater.vvb"}, t0 + timedelta(seconds=30 * i), 2.0, 1.5, -2000, True))
    assert ha.calls == []

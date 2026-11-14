"""Stop selling at negative prices: only in control, the owner's value remembered and put back afterwards."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from energy_pilot.curtail import Curtail, candidates


class HA:
    def __init__(self):
        self.states = {"number.growatt_export_limit": {"state": "100", "attributes": {"unit_of_measurement": "%"}},
                       "sensor.other": {"state": "1"}}
        self.calls = []

    async def call_service(self, dom, svc, data):
        self.calls.append((dom, svc, data))
        self.states[data["entity_id"]]["state"] = str(data.get("value"))


class Ov:
    def __init__(self, ha, sell):
        self.ha = ha
        self.settings = {"curtail": {"on": True, "entity": "number.growatt_export_limit", "value": 0}}
        self.engine = SimpleNamespace(tz=timezone.utc, sell_prices=lambda: {datetime(2020, 1, 1, tzinfo=timezone.utc): sell[0]},
                                      sell_at=lambda p, w, f: list(p.values())[0])

    def save(self, d):
        self.settings.update(d)

    def plan(self):
        return {}


def run(mode, prices):
    ha, sell = HA(), [0.0]
    ov = Ov(ha, sell)
    c = Curtail(ha, ov, SimpleNamespace(mode=lambda p: mode))
    for p in prices:
        sell[0] = p
        asyncio.run(c.tick())
    return ha, ov, c


def test_found():
    assert [x["entity_id"] for x in candidates(HA().states)] == ["number.growatt_export_limit"]


def test_stops_and_puts_back():
    ha, ov, _ = run("control", [0.5, -0.1, -0.2, 0.3])
    assert [c[2]["value"] for c in ha.calls] == [0, 100]
    assert ha.states["number.growatt_export_limit"]["state"] == "100"
    assert ov.settings["curtail_saved"] is None


def test_shadow_does_nothing():
    ha, _, c = run("shadow", [-0.5])
    assert ha.calls == [] and c.last["want"] is True


def test_off_does_nothing():
    ha, sell = HA(), [-1.0]
    ov = Ov(ha, sell)
    ov.settings["curtail"]["on"] = False
    asyncio.run(Curtail(ha, ov, SimpleNamespace(mode=lambda p: "control")).tick())
    assert ha.calls == []

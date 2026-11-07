"""The runner with a pretend Home Assistant: shadow never calls a service or writes a state."""

import asyncio
from pathlib import Path

import pytest

from energy_pilot.runner import CONTROL, SHADOW, Runner


class FakeHA:
    def __init__(self):
        self.states = {"sensor.soc": {"entity_id": "sensor.soc", "state": "40", "attributes": {}},
                       "sensor.demo_plan": {"entity_id": "sensor.demo_plan", "state": "charge", "attributes": {}}}
        self.on_state = []
        self.connected = asyncio.Event()
        self.connected.set()
        self.config = {"time_zone": "Europe/Copenhagen", "version": "test"}
        self.calls, self.written = [], []

    async def call_service(self, domain, service, data, response=False):
        self.calls.append((domain, service, data))
        return {"response": {"ok": True}} if response else {"context": {}}

    async def set_state(self, entity_id, state, attributes):
        self.written.append((entity_id, state))

    async def listen_event(self, event, cb):
        pass

    def change(self, entity_id, state):
        old = self.states[entity_id]
        new = {**old, "state": state}
        self.states[entity_id] = new
        for cb in self.on_state:
            cb(entity_id, old, new)


async def settle():
    for _ in range(20):
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_shadow_does_nothing_but_knows_what_it_would_do(tmp_path):
    ha = FakeHA()
    runner = Runner(ha, Path(__file__).parent / "apps", tmp_path, [{"name": "demo", "module": "demo", "class": "Demo"}])
    await runner.start()
    await settle()
    assert runner.mode("demo") == SHADOW
    assert ha.calls == [] and ha.written == []
    app = runner.apps["demo"]
    assert app.would[-1]["service"] == "number.set_value" and app.would[-1]["data"]["value"] == 50.0
    # It sees what it would have set, as if it had happened
    assert runner.state_of("demo", "number.battery_target")["state"] == "50.0"
    assert runner.state_of("demo", "sensor.demo_plan")["state"] == "charge"
    # Its files go to Energy Pilot's folder, not /config
    assert (tmp_path / "demo_state.json").exists()
    # Compared with the running system: same plan
    st = runner.status()["apps"][0]
    assert st["agree"] == 100
    ha.change("sensor.soc", "70")
    await settle()
    assert app.instance.seen == ["70"]
    assert runner.state_of("demo", "sensor.demo_plan")["state"] == "hold"
    assert runner.status()["apps"][0]["agree"] < 100  # the running system still says "charge"
    runner.stop()


@pytest.mark.asyncio
async def test_control_acts(tmp_path):
    ha = FakeHA()
    (tmp_path / "energy_pilot_modes.json").write_text('{"demo": "control"}')
    runner = Runner(ha, Path(__file__).parent / "apps", tmp_path, [{"name": "demo", "module": "demo", "class": "Demo"}])
    await runner.start()
    await settle()
    assert runner.mode("demo") == CONTROL
    assert ha.calls and ha.calls[-1][1] == "set_value"
    assert ("sensor.demo_plan", "charge") in ha.written
    runner.all_to_shadow()
    assert runner.mode("demo") == SHADOW
    runner.stop()

"""A value that held and then changed by itself is set again at once; when it keeps happening, the user is told
something else steers too. Predbat in a control mode is named."""

import asyncio
import time

from energy_pilot import control as C


class FakeHA:
    def __init__(self, states):
        self.states, self.sent = states, []

    async def call_service(self, domain, service, data):
        self.sent.append(data["entity_id"])
        self.states[data["entity_id"]] = {"state": str(data.get("option", data.get("value")))}


def ctl_with(ha, key="growatt"):
    c = C.Controller.__new__(C.Controller)
    c.ha, c.last, c.log, c.drift = ha, {}, {}, {}
    want = {"intent": "hold", "ctx": {"soc": 50}}
    call = {"domain": "select", "service": "select_option", "data": {"entity_id": "select.mode", "option": "Hold"}}
    c.intents = lambda: {"battery": want}
    c.mode = lambda part: "control"
    c.calls = lambda part, w: [dict(call, data=dict(call["data"]))]
    c.blocked = lambda part: None
    c.profile_key = lambda part="battery": key
    c.is_battery = lambda part: True
    c._restore = lambda part, intent: []
    c._pool = lambda part="battery": ["select.mode"]
    c.ov = type("O", (), {"settings": {}})()
    return c


def test_set_again_when_changed_back(monkeypatch):
    async def fast(_):
        return None
    monkeypatch.setattr(C.asyncio, "sleep", fast)
    ha = FakeHA({"select.mode": {"state": "Normal"}})
    c = ctl_with(ha)
    asyncio.run(c.tick())
    assert ha.sent == ["select.mode"]
    asyncio.run(c.tick())  # holds: nothing sent
    assert ha.sent == ["select.mode"]
    for _ in range(3):  # something else puts it back, three times
        ha.states["select.mode"] = {"state": "Normal"}
        c.last["battery"]["t"] = time.time() - 120
        asyncio.run(c.tick())
    assert ha.sent.count("select.mode") == 4
    assert [x["key"] for x in c.watch_checks()] == ["other_control"]


def test_victron_resetting_itself_is_not_another_system(monkeypatch):
    async def fast(_):
        return None
    monkeypatch.setattr(C.asyncio, "sleep", fast)
    ha = FakeHA({"select.mode": {"state": "Normal"}})
    c = ctl_with(ha, "victron")
    asyncio.run(c.tick())
    for _ in range(3):
        ha.states["select.mode"] = {"state": "Normal"}
        c.last["battery"]["t"] = time.time() - 120
        asyncio.run(c.tick())
    assert ha.sent.count("select.mode") == 4  # still set again
    assert c.watch_checks() == []


def test_predbat_in_control_is_named():
    ha = FakeHA({"select.predbat_mode": {"state": "Control charge & discharge"}})
    c = ctl_with(ha)
    assert c.watch_checks()[0]["key"] == "predbat_on"
    ha.states["select.predbat_mode"] = {"state": "Monitor"}
    assert c.watch_checks() == []

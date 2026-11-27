"""Shadow chosen while a round is writing: the hand-back has the last word, the old order is never put back."""

import asyncio
from types import SimpleNamespace

import pytest

from energy_pilot import control as C


def _ctl(states, log):
    async def call_service(domain, service, data):
        states[data["entity_id"]] = {"state": str(data.get("option", data.get("value")))}
        log.append((data["entity_id"], data.get("option", data.get("value"))))

    c = C.Controller.__new__(C.Controller)
    c.ha = SimpleNamespace(states=states, call_service=call_service, config={"time_zone": "UTC"})
    c.ov = SimpleNamespace(settings={"control": {"battery": "control"}}, role=lambda r: None)
    c.ov.save = lambda d: c.ov.settings.update(d)
    c.intents = lambda: {"battery": {"intent": "charge", "ctx": {}}}

    def calls(part, w):
        on = w["intent"] == "charge"
        return [{"domain": "select", "service": "select_option", "data": {"entity_id": "select.mode", "option": "battery_first" if on else "load_first"}},
                {"domain": "number", "service": "set_value", "data": {"entity_id": "number.rate", "value": 100 if on else 0}}]
    c.calls = calls
    c._restore = lambda p, i: []
    c._prof = lambda p: {}
    c.blocked = lambda p: None
    c.bat_parts = lambda: []
    c.car_parts = lambda: []
    c.parts = lambda: ["battery"]
    c.is_battery = lambda p: p == "battery"
    c.last, c.log = {}, {}
    c._observe = lambda: None
    return c


@pytest.mark.asyncio
async def test_hand_back_during_a_round_ends_normal(monkeypatch):
    real_sleep = asyncio.sleep
    monkeypatch.setattr(C.asyncio, "sleep", lambda s: real_sleep(s / 100))
    states = {"select.mode": {"state": "load_first"}, "number.rate": {"state": "0"}}
    log = []
    c = _ctl(states, log)
    t = asyncio.create_task(c.tick())  # the main loop writing "charge"
    await real_sleep(0.005)  # in the middle of it
    await c.hand_back("battery")  # the user presses shadow (web.control_mode)
    c.set_mode("battery", "shadow")
    await c.tick()
    await t
    assert states["select.mode"]["state"] == "load_first" and states["number.rate"]["state"] == "0"
    assert log[-1] == ("number.rate", 0)


@pytest.mark.asyncio
async def test_a_round_waiting_for_the_lock_gives_way(monkeypatch):
    real_sleep = asyncio.sleep
    monkeypatch.setattr(C.asyncio, "sleep", lambda s: real_sleep(s / 100))
    states = {"select.mode": {"state": "load_first"}, "number.rate": {"state": "0"}}
    log = []
    c = _ctl(states, log)
    c.set_mode("battery", "control")
    hb = asyncio.create_task(c.hand_back("battery"))  # holds the lock, already "normal"
    await real_sleep(0)
    await c.tick()  # a round that read "control" before: writes nothing
    await hb
    assert "battery_first" not in [v for _, v in log]


@pytest.mark.asyncio
async def test_release_during_a_round_ends_normal(monkeypatch):
    real_sleep = asyncio.sleep
    monkeypatch.setattr(C.asyncio, "sleep", lambda s: real_sleep(s / 100))
    states = {"select.mode": {"state": "load_first"}, "number.rate": {"state": "0"}}
    log = []
    c = _ctl(states, log)
    c._charger_hand_back = lambda p: []
    t = asyncio.create_task(c.tick())
    await real_sleep(0.005)
    await c.release()
    await t
    assert states["select.mode"]["state"] == "load_first" and c.mode("battery") == "shadow"

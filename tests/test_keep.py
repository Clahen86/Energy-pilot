"""Victron forgets its ESS settings: the last values are sent again every 4 minutes, at once when the controls are
back after being unavailable, and each resend is counted in the log."""

import asyncio
from collections import deque
import time
from types import SimpleNamespace

from energy_pilot import control as C

CALL = {"domain": "number", "service": "set_value", "data": {"entity_id": "number.ess_ac_grid_setpoint", "value": -4400}}


def ctl(state="-4400"):
    c = C.Controller.__new__(C.Controller)
    sent = []

    async def call_service(domain, service, data):
        sent.append(data)

    c.ha = SimpleNamespace(states={"number.ess_ac_grid_setpoint": {"state": state}}, call_service=call_service)
    c.ov = SimpleNamespace(settings={"control": {"battery": "control"}}, save=lambda d: None)
    c.profile_key = lambda *a: "victron"
    c.bat_parts = lambda: []
    c.blocked = lambda part: None
    c._gone, c._bat_lock = {}, asyncio.Lock()
    entry = {"t": time.time(), "intent": "export", "ctx": {}, "calls": [CALL], "mode": "control", "result": "ok"}
    c.last = {"battery": entry}
    c.log = {"battery": deque([entry])}
    return c, sent


def run(c):
    async def go():
        orig = asyncio.sleep
        C.asyncio.sleep = lambda *_a: orig(0)
        try:
            await c.keep()
        finally:
            C.asyncio.sleep = orig
    asyncio.run(go())


def test_sent_again_after_4_minutes_even_when_ha_shows_the_value():
    c, sent = ctl()
    run(c)
    assert sent == []  # just sent
    c.last["battery"]["t"] -= 250
    run(c)
    assert sent == [CALL["data"]]  # written although HA shows -4400: Victron forgets it
    assert c.log["battery"][0]["resent"] == 1 and c.log["battery"][0]["resent_last"]["why"] == "due"


def test_sent_at_once_when_the_control_is_back():
    c, sent = ctl("unavailable")
    run(c)
    assert sent == []  # can't write while it's away
    c.ha.states["number.ess_ac_grid_setpoint"]["state"] = "-4400"
    run(c)
    assert sent == [CALL["data"]]
    assert c.log["battery"][0]["resent_last"]["why"] == "back"


def test_shadow_is_left_alone():
    c, sent = ctl()
    c.ov.settings["control"]["battery"] = "shadow"
    c.last["battery"]["t"] -= 999
    run(c)
    assert sent == []

"""Automatic updates: only Home Assistant's own switch, only when the user says yes, and none outside HA OS."""
import asyncio

from energy_pilot import autoupdate


def test_no_supervisor_no_switch(monkeypatch):
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    autoupdate._cache.update(t=0.0, on=None)
    assert asyncio.run(autoupdate.state()) is None
    assert asyncio.run(autoupdate.turn_on()) is False


def test_turn_on_asks_for_auto_update_only(monkeypatch):
    sent = {}

    class Resp:
        status = 200
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def post(self, url, headers=None, json=None, timeout=None):
            sent.update(url=url, json=json)
            return Resp()

    monkeypatch.setenv("SUPERVISOR_TOKEN", "x")
    monkeypatch.setattr(autoupdate.aiohttp, "ClientSession", Session)
    assert asyncio.run(autoupdate.turn_on()) is True
    assert sent == {"url": "http://supervisor/addons/self/options", "json": {"auto_update": True}}
    assert asyncio.run(autoupdate.state()) is True  # remembered: the card goes away at once

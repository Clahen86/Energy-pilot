"""Orders run out by themselves: the inverter's time slot is a lease of 60-75 minutes, moved on every quarter."""
import asyncio
from datetime import datetime
from types import SimpleNamespace

from energy_pilot import adapters
from energy_pilot.control import Controller


def test_lease_from_this_quarter():
    w = adapters.alpha_windows(datetime(2026, 11, 21, 14, 7))
    assert w["lease_from"] == "14:00" and w["lease_to"] == "15:15"


def test_lease_never_past_midnight():
    assert adapters.alpha_windows(datetime(2026, 11, 21, 23, 20))["lease_to"] == "23:59"
    assert adapters.alpha_windows(datetime(2026, 11, 21, 0, 2))["lease_from"] == "00:00"


def test_growatt_charge_and_export_use_the_lease():
    p = adapters.PROFILES["growatt"]
    for intent in ("charge", "export"):
        vals = [v for _, _, v in p[intent]]
        assert "{lease_from}" in vals and "{lease_to}" in vals and "23:59" not in vals


def test_let_go_sends_normal_without_waiting():
    sent = []

    class HA:
        states = {}

        async def call_service(self, d, s, data):
            sent.append((d, s, data.get("entity_id")))

    ctl = Controller.__new__(Controller)
    ctl.ha = HA()
    ctl.ov = SimpleNamespace(settings={"control": {"battery": "control"}})
    ctl.intents = lambda: {"battery": {"intent": "charge", "ctx": {}}}
    ctl.bat_parts = lambda: []
    ctl.blocked = lambda part: None
    ctl.calls = lambda part, want: [{"domain": "select", "service": "select_option",
                                     "data": {"entity_id": "select.x_work_mode_priority", "option": "Load first"}}] if want["intent"] == "normal" else []
    ctl._restore = lambda part, intent: []
    ctl._matches = lambda c: False
    asyncio.run(ctl.let_go(budget_s=2))
    assert sent == [("select", "select_option", "select.x_work_mode_priority")]

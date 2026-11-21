"""Orders run out by themselves: the inverter's time slot ends with the plan's block (at most 3-4 h ahead), or after
60-75 minutes without one. It starts a little before now and stays put while the block lasts."""
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from types import SimpleNamespace

from energy_pilot import adapters
from energy_pilot.control import Controller


def test_lease_starts_before_this_quarter():
    w = adapters.alpha_windows(datetime(2026, 11, 21, 14, 7))
    assert w["lease_from"] == "12:00" and w["lease_to"] == "15:15"  # 2 h back: a slow clock is inside it too


def test_a_block_is_written_once_and_left_alone():
    """21 November: the Growatt went back to Load first each time its slot was moved to start at the quarter now."""
    start = adapters.window_start(datetime(2026, 11, 21, 12, 15))
    end = datetime(2026, 11, 21, 14, 45)
    seen = {(w["lease_from"], w["lease_to"]) for w in (adapters.alpha_windows(datetime(2026, 11, 21, 12, m), start, end)
                                                         for m in (15, 20, 31, 45, 59))}
    assert seen == {("10:15", "16:45")}  # the same all the way through, 2 h past the block for a fast clock
    long_end = datetime(2026, 11, 21, 20, 0)  # a long block: never more than 3-4 h ahead
    assert adapters.alpha_windows(datetime(2026, 11, 21, 12, 15), start, long_end)["lease_to"] == "18:00"
    w = adapters.alpha_windows(datetime(2026, 11, 21, 12, 15), start, end)
    assert w["now_to"] == "14:45"  # Alpha's cloud window: the block itself
    assert adapters.alpha_windows(datetime(2026, 11, 21, 12, 15), datetime(2026, 11, 21, 13, 0), end)["lease_from"] == "10:15"


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


def test_controller_keeps_the_block_start_and_follows_the_plan_end():
    ctl = Controller.__new__(Controller)
    ctl.ha = SimpleNamespace(config={"time_zone": "Europe/Copenhagen"})
    now = datetime.now(ZoneInfo("Europe/Copenhagen"))
    q = adapters.quarter(now)
    steps = [{"t": (q + timedelta(minutes=15 * i)).isoformat(), "action": "charge_grid" if i < 6 else "hold"} for i in range(10)]
    b = {"steps": steps, "slot_min": 15}
    w1 = ctl._windows(b, steps[0])
    w2 = ctl._windows({"steps": steps[1:], "slot_min": 15}, steps[1])  # a quarter on: the same block
    lead = max(adapters.window_start(now) - timedelta(minutes=adapters.LEASE_LEAD_MIN), q.replace(hour=0, minute=0))
    assert w1["lease_from"] == w2["lease_from"] == lead.strftime("%H:%M")
    if (q + timedelta(minutes=210)).date() == q.date():
        assert w1["lease_to"] == w2["lease_to"] == (q + timedelta(minutes=210)).strftime("%H:%M")
    ctl._windows(b, {"action": "hold"})  # another action: the next charge block starts afresh
    assert ctl._block[0] == "hold"


def test_the_dst_note_only_where_the_clocks_change():
    ctl = Controller.__new__(Controller)
    ctl.profile_key = lambda part="battery": "growatt"
    ctl.ha = SimpleNamespace(config={"time_zone": "Asia/Kolkata"})  # no summer time
    assert ctl._dst_note() is None
    import energy_pilot.control as C

    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 28, 12, 0, tzinfo=tz)
    old = C.datetime
    C.datetime = Fixed
    try:
        ctl.ha = SimpleNamespace(config={"time_zone": "Europe/Copenhagen"})  # winter time from 25 October
        assert ctl._dst_note()["key"] == "clock_dst"
        ctl.ha = SimpleNamespace(config={"time_zone": "Asia/Kolkata"})
        assert ctl._dst_note() is None
        ctl.ha = SimpleNamespace(config={"time_zone": "Europe/Copenhagen"})
        ctl.profile_key = lambda part="battery": "victron"  # no time slots: nothing to say
        assert ctl._dst_note() is None
    finally:
        C.datetime = old


def test_a_slot_the_inverter_left_is_found_within_a_minute():
    import time as _t
    ctl = Controller.__new__(Controller)
    called = []

    async def tick(parts=None):
        called.append(parts)
    ctl.tick = tick
    ctl.mode = lambda part: "control"
    ctl.blocked = lambda part: None
    ctl.testing = set()
    ctl._lock = lambda: asyncio.Lock()
    call = {"domain": "select", "service": "select_option", "data": {"entity_id": "select.x_work_mode_priority", "option": "Battery first"}}
    ctl.last = {"battery": {"t": _t.time() - 120, "result": "ok", "calls": [call]}}
    ctl._matches = lambda c: True
    asyncio.run(ctl.recheck())
    assert called == []  # all as told: nothing to do
    ctl._matches = lambda c: False  # back on Load first by itself
    asyncio.run(ctl.recheck())
    assert called == [("battery",)]

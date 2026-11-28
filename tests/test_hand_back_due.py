"""A battery's way back to normal that the inverter didn't take is tried again until it does (also after a restart),
and a chosen sensor that is gone is never replaced by a guess while Energy Pilot steers the battery."""

import asyncio
import time
from types import SimpleNamespace

import pytest

from energy_pilot import control as C
from energy_pilot import overview as O


def _ctl(states, log, drop=0):
    """drop: how many writes the inverter loses (Solarman drops a write now and then)."""
    left = {"n": drop}

    async def call_service(domain, service, data):
        log.append((data["entity_id"], data.get("option", data.get("value"))))
        if left["n"] > 0:
            left["n"] -= 1
            return  # sent, but not taken
        states[data["entity_id"]] = {"state": str(data.get("option", data.get("value")))}

    c = C.Controller.__new__(C.Controller)
    c.ha = SimpleNamespace(states=states, call_service=call_service, config={"time_zone": "UTC"})
    c.ov = SimpleNamespace(settings={"control": {"battery": "control"}}, role=lambda r: None, flow=lambda: {"soc": 50})
    c.ov.save = lambda d: c.ov.settings.update(d)
    c.intents = lambda: {"battery": {"intent": "charge", "ctx": {}}}
    c.calls = lambda part, w: [{"domain": "select", "service": "select_option",
                                "data": {"entity_id": "select.mode", "option": "battery_first" if w["intent"] == "charge" else "load_first"}}]
    c._restore = lambda p, i: []
    c.blocked = lambda p: None
    c.bat_parts = lambda: []
    c.car_parts = lambda: []
    c.parts = lambda: ["battery"]
    c.last, c.log = {}, {}
    c.drift, c.car_stuck = {}, {}
    c.profile_key = lambda part="battery": None
    return c


@pytest.fixture
def fast(monkeypatch):
    real_sleep = asyncio.sleep
    monkeypatch.setattr(C.asyncio, "sleep", lambda s: real_sleep(0))


@pytest.mark.asyncio
async def test_a_hand_back_not_taken_is_kept_and_finished_later(fast):
    states = {"select.mode": {"state": "battery_first"}}
    c = _ctl(states, [], drop=2)  # both tries of the hand-back are lost
    await c.hand_back("battery")
    c.set_mode("battery", "shadow")
    due = c.ov.settings["hand_back_due"]["battery"]
    assert states["select.mode"]["state"] == "battery_first" and due["tries"] == 1
    # (a restart keeps it: it's in the settings) - the minute's check sends it again once its time has come
    await c.finish_hand_back()
    assert states["select.mode"]["state"] == "battery_first"  # not yet: a minute between tries
    c.ov.settings["hand_back_due"]["battery"]["next"] = 0
    await c.finish_hand_back()
    assert states["select.mode"]["state"] == "load_first"
    assert c.ov.settings["hand_back_due"] == {}


@pytest.mark.asyncio
async def test_a_hand_back_that_takes_leaves_nothing(fast):
    states = {"select.mode": {"state": "battery_first"}}
    c = _ctl(states, [])
    await c.hand_back("battery")
    assert states["select.mode"]["state"] == "load_first"
    assert not c.ov.settings.get("hand_back_due")


@pytest.mark.asyncio
async def test_control_again_drops_it_and_a_day_gives_up(fast):
    states = {"select.mode": {"state": "battery_first"}}
    c = _ctl(states, [], drop=99)
    await c.hand_back("battery")
    c.set_mode("battery", "shadow")
    assert "battery" in c.ov.settings["hand_back_due"]
    c.set_mode("battery", "control")  # its own round sets the battery now
    assert c.ov.settings["hand_back_due"] == {}
    c.ov.settings["hand_back_due"] = {"battery": {"calls": c.calls("battery", {"intent": "normal"}), "since": time.time() - 25 * 3600,
                                                  "tries": 500, "next": 0}}
    c.set_mode("battery", "shadow")
    log = []
    c.ha.call_service = lambda *a: log.append(a)
    await c.finish_hand_back()
    assert log == [] and c.ov.settings["hand_back_due"] == {}


@pytest.mark.asyncio
async def test_the_owner_is_told_after_a_second_miss(fast):
    states = {"select.mode": {"state": "battery_first"}}
    c = _ctl(states, [], drop=99)
    c.ov.settings["hand_back_due"] = {"battery": {"calls": c.calls("battery", {"intent": "normal"}), "since": time.time(), "tries": 1, "next": 0}}
    c.set_mode("battery", "shadow")
    assert not any(w["key"] == "hand_back_open" for w in c.watch_checks())
    await c.finish_hand_back()
    assert c.ov.settings["hand_back_due"]["battery"]["tries"] == 2
    assert any(w["key"] == "hand_back_open" for w in c.watch_checks())


# ---------- a chosen sensor that is gone ----------

def _ov(states, mode):
    ov = O.Overview.__new__(O.Overview)
    ov.ha = SimpleNamespace(states=states, config={"time_zone": "UTC"})
    ov.settings = {"roles": {"battery_soc": "sensor.old_soc"}, "control": {"battery": mode}}
    ov.detected = {"battery_soc": {"entity_id": "sensor.other_soc"}}
    ov.controller = SimpleNamespace(mode=lambda p: ov.settings["control"].get(p, "shadow"), bat_parts=lambda: [])
    return ov


def test_no_guess_while_controlling_but_in_shadow():
    states = {"sensor.other_soc": {"state": "77"}}  # the chosen one was renamed away
    assert _ov(states, "control").role("battery_soc") is None
    assert _ov(states, "shadow").role("battery_soc") == "sensor.other_soc"  # nothing is steered: a guess may show
    assert _ov(states, "control").role_found("battery_soc") == "sensor.other_soc"  # (autofix's rename still finds it)
    states["sensor.old_soc"] = {"state": "50"}
    assert _ov(states, "control").role("battery_soc") == "sensor.old_soc"
    assert _ov(states, "control").gone_roles() == {}


def test_the_guard_runs_the_battery_as_normal_when_a_sensor_is_gone():
    c = C.Controller.__new__(C.Controller)
    c.ha = SimpleNamespace(config={"time_zone": "UTC"}, states={})
    c.engine = None
    c.ov = SimpleNamespace(flow=lambda: {"soc": 50}, gone_roles=lambda: {"grid_power": ["sensor.grid_old"]},
                           settings={"control": {"battery": "control"}})
    out = c._guard("battery", {"intent": "charge", "ctx": {"power_w": 3000}})
    assert out["intent"] == "normal"
    c.bat_parts = lambda: []
    c.drift, c.car_stuck = {}, {}
    c.profile_key = lambda part="battery": None
    w = [x for x in c.watch_checks() if x["key"] == "sensor_gone"]
    assert w and "sensor.grid_old" in w[0]["vals"]["list"]


@pytest.mark.asyncio
async def test_one_battery_never_wipes_another(fast):
    states = {"select.mode": {"state": "battery_first"}}
    c = _ctl(states, [], drop=99)
    c.set_mode("battery", "shadow")
    c.ov.settings["hand_back_due"] = {"battery": {"calls": c.calls("battery", {"intent": "normal"}), "since": time.time(), "tries": 1, "next": 0}}
    real = c._send

    async def send_and_bat2_fails_meanwhile(calls, *a, **k):
        c._due_set("bat2", {"calls": calls, "since": time.time(), "tries": 1, "next": time.time() + 60})
        return await real(calls, *a, **k)
    c._send = send_and_bat2_fails_meanwhile
    await c.finish_hand_back()
    assert set(c.ov.settings["hand_back_due"]) == {"battery", "bat2"}


def test_level_unknown_after_an_order_runs_the_battery_as_normal():
    from energy_pilot.engine import Battery

    bat = Battery(capacity_kwh=10, max_charge_kw=5, max_discharge_kw=5, min_soc=10)
    c = C.Controller.__new__(C.Controller)
    c.engine = SimpleNamespace(result={}, settings=lambda: bat)  # the plan is gone: the level is unknown
    c.ov = SimpleNamespace(flow=lambda: {"soc": None}, settings={"inverter_profile": "growatt"},
                           price_info={"none": False}, sell_sun=lambda: False, ev=lambda: None)
    c.ha = SimpleNamespace(config={"time_zone": "UTC"})
    c.car_why = ""
    c.bat_parts = lambda: []
    c.last = {"battery": {"intent": "charge"}}
    assert c.intents()["battery"]["intent"] == "normal"
    c.last = {}
    assert "battery" not in c.intents()  # nothing was ordered: nothing to undo

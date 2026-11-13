"""Mistakes mended by themselves - only ones that can't cost money - and the battery put to normal when it does the
opposite of what it was told."""

import asyncio
from types import SimpleNamespace
import time

from energy_pilot import autofix as A
from energy_pilot import control as C


def ov(settings=None, states=None, country="DK", roles=None):
    store = dict(settings or {})
    o = SimpleNamespace(settings=store, save=lambda d: store.update(d),
                        ha=SimpleNamespace(states=states or {}, config={"country": country, "currency": "DKK"}))
    o.roles = lambda: dict(roles or {})
    o.role = lambda name: (roles or {}).get(name)
    o.candidates = lambda: {}
    o.fine_prices = {}
    return o, store


def test_fuse_in_amps_is_turned_into_kw():
    o, store = ov({"import_limit_kw": 75}, country="GB")  # the UK tester's 80 A fuse, written as 75
    A.AutoFix(o).run()
    assert store["import_limit_kw"] == 16 and store["autofix_log"][0]["what"] == "fuse"
    o, store = ov({"import_limit_kw": 25}, country="DK")
    A.AutoFix(o).run()
    assert store["import_limit_kw"] == 25  # a real kW value is left alone
    o, store = ov({"import_limit_kw": 63})
    A.AutoFix(o).run()
    assert store["import_limit_kw"] == 40  # 63 A on three phases


def test_undo_puts_it_back_and_it_is_not_done_again():
    o, store = ov({"import_limit_kw": 75}, country="GB")
    a = A.AutoFix(o)
    a.run()
    a.undo("fuse")
    assert store["import_limit_kw"] == 75 and store["autofix_log"] == []
    a.run()
    assert store["import_limit_kw"] == 75


def test_battery_level_as_a_fraction():
    states = {"sensor.soc": {"state": "0.5"}}
    o, store = ov(states=states, roles={"battery_soc": "sensor.soc"})
    a = A.AutoFix(o)
    for i in range(30):
        states["sensor.soc"]["state"] = str(0.5 + i / 100)
        a.run()
    assert store["role_scale"] == {"battery_soc": 100}


def test_power_in_kw_without_saying_so():
    states = {"sensor.grid": {"state": "1500"}, "sensor.batt": {"state": "1.5"}}
    o, store = ov(states=states, roles={"grid_power": "sensor.grid", "battery_power": "sensor.batt"})
    a = A.AutoFix(o)
    for i in range(60):
        states["sensor.grid"]["state"] = str(1500 + i * 10)
        states["sensor.batt"]["state"] = str(1.5 + i / 37)
        a.run()
    assert store["role_scale"] == {"battery_power": 1000}


def test_price_in_ore():
    o, store = ov()
    o.fine_prices = {i: 250.0 + i for i in range(24)}
    A.AutoFix(o).run()
    assert store["price_scale"] == 0.01


def test_a_renamed_sensor_is_followed():
    o, store = ov({"roles": {"grid_power": "sensor.old_grid"}}, states={"sensor.new_grid": {"state": "1"}},
                  roles={"grid_power": "sensor.new_grid"})
    a = A.AutoFix(o)
    a.run()
    assert store["roles"]["grid_power"] == "sensor.old_grid"  # waits a while first
    a.gone_since["renamed:grid_power"] -= 3600
    a.run()
    assert store["roles"]["grid_power"] == "sensor.new_grid"


def test_battery_doing_the_opposite_goes_to_normal():
    sent = []

    async def call_service(domain, service, data):
        sent.append(data)

    c = C.Controller.__new__(C.Controller)
    store = {"control": {"battery": "control"}}
    flow = {"battery": -2000, "grid": 0, "soc": 50}
    c.ha = SimpleNamespace(states={}, call_service=call_service)
    c.ov = SimpleNamespace(settings=store, save=lambda d: store.update(d), flow=lambda: flow)
    c.testing, c.safe_until, c._wrong, c._car_idle, c._kicked, c.car_stuck = set(), {}, {}, {}, {}, {}
    c.blocked = lambda p: None
    c.bat_parts = lambda: []
    c.last = {"battery": {"t": time.time() - 3600, "intent": "charge", "ctx": {}, "calls": [], "mode": "control", "result": "ok"}}
    ticked = []

    async def tick(parts=None):
        ticked.append(parts)
    c.tick = tick
    asyncio.run(c.guard())
    assert not c.safe_until  # not at once
    c._wrong["battery"] -= C.Controller.WRONG_S + 1
    asyncio.run(c.guard())
    assert c.safe_until["battery"] > time.time() and ticked == [("battery",)]
    assert C.Controller._opposite("charge", {"battery": 200}) is False  # slow, not opposite

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


def test_an_idle_battery_in_watts_is_not_taken_for_kw():
    # The UK Victron tester: "Total Battery Net Power" in W sat at a few watts overnight and was multiplied by 1000 -
    # the house then looked like 858 kW and nothing was sold.
    states = {"sensor.grid": {"state": "1500"}, "sensor.batt": {"state": "5.3", "attributes": {"unit_of_measurement": "W"}}}
    o, store = ov(states=states, roles={"grid_power": "sensor.grid", "battery_power": "sensor.batt"})
    a = A.AutoFix(o)
    for i in range(60):
        states["sensor.grid"]["state"] = str(1500 + i * 10)
        states["sensor.batt"]["state"] = str(5.3 + i / 37)
        a.run()
    assert not store.get("role_scale")


def test_a_wrong_kw_guess_is_put_back_when_the_sensor_reads_hundreds():
    states = {"sensor.grid": {"state": "15"}, "sensor.batt": {"state": "-858", "attributes": {"unit_of_measurement": "W"}}}
    o, store = ov({"role_scale": {"battery_power": 1000},
                   "autofix_log": [{"key": "kw:battery_power", "what": "kw_scale", "from": 1, "to": 1000, "t": 0}]},
                  states=states, roles={"grid_power": "sensor.grid", "battery_power": "sensor.batt"})
    a = A.AutoFix(o)
    a.run()
    assert store["role_scale"] == {} and store["autofix_log"] == []
    assert "kw:battery_power" in store["autofix_ignore"]  # never guessed again for this sensor


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


def test_a_stuck_house_meter_is_not_swapped_for_one_phase():
    # Deye: "load_totalpower" stuck, and the first other meter found was "Load L1 Power" - a third of the house
    from datetime import datetime, timedelta, timezone

    fresh = datetime.now(timezone.utc).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
    states = {"sensor.load_totalpower": {"state": "800", "last_changed": old},
              "sensor.inverter_load_l1_power": {"state": "400", "last_changed": fresh},
              "sensor.inverter_load_power": {"state": "1200", "last_changed": fresh}}
    roles = {"house_power": "sensor.load_totalpower"}
    o, store = ov({"roles": dict(roles)}, states=states, roles=roles)
    o.candidates = lambda: {"house_power": [{"entity_id": "sensor.inverter_load_l1_power", "guess": True},
                                            {"entity_id": "sensor.inverter_load_power", "guess": True}]}
    A.AutoFix(o).run()
    assert store["roles"]["house_power"] == "sensor.inverter_load_power"
    # on one phase (the UK) the L1 meter is the whole house
    o, store = ov({"roles": dict(roles)}, states=states, roles=roles, country="GB")
    o.candidates = lambda: {"house_power": [{"entity_id": "sensor.inverter_load_l1_power", "guess": True}]}
    A.AutoFix(o).run()
    assert store["roles"]["house_power"] == "sensor.inverter_load_l1_power"


def test_unavailable_battery_level_is_swapped_after_half_an_hour():
    from datetime import datetime, timezone

    fresh = datetime.now(timezone.utc).isoformat()
    states = {"sensor.old_soc": {"state": "unavailable", "last_changed": fresh},
              "sensor.new_soc": {"state": "64", "last_changed": fresh, "attributes": {"friendly_name": "Battery SOC"}}}
    o, store = ov({"roles": {"battery_soc": "sensor.old_soc"}}, states, roles={"battery_soc": "sensor.old_soc"})
    o.candidates = lambda: {"battery_soc": [{"entity_id": "sensor.new_soc", "guess": True}]}
    a = A.AutoFix(o)
    a.run()
    assert store["roles"]["battery_soc"] == "sensor.old_soc"  # not at once
    a.gone_since["gone:battery_soc"] -= A.GONE_S + 1
    a.run()
    assert store["roles"]["battery_soc"] == "sensor.new_soc" and store["autofix_log"][-1]["what"] == "gone"
    states["sensor.old_soc"]["state"] = "55"  # an idle level that sits still is never swapped
    o2, store2 = ov({"roles": {"battery_soc": "sensor.old_soc"}}, states, roles={"battery_soc": "sensor.old_soc"})
    A.AutoFix(o2).run()
    assert store2["roles"]["battery_soc"] == "sensor.old_soc"


def test_fuse_from_the_inverter_while_still_the_start_value():
    """Kostal's House Fuse Size (50 A): the 10 kW new installs start with becomes 32 kW (50 A × 230 V × 3, a bit under)."""
    amps = {"v": 50.0}
    o, store = ov({"import_limit_kw": 10})
    o.controller = SimpleNamespace(fuse_amps=lambda: amps["v"])
    a = A.AutoFix(o)
    a.run()
    assert store["import_limit_kw"] == 32 and store["autofix_log"][-1]["what"] == "fuse_inv"
    amps["v"] = 35.0  # changed in the integration: follows, while the limit is still what it set
    a.run()
    assert store["import_limit_kw"] == 22 and store["autofix_log"][-1]["from"] == 10
    a.undo("fuse_inverter")  # back to the 10 kW, and never again
    a.run()
    assert store["import_limit_kw"] == 10


def test_ok_hides_the_line_but_keeps_the_fix():
    """OK: the fuse stays at 32 kW and the line goes; a new fix (the fuse changed in the inverter) shows again."""
    amps = {"v": 50.0}
    o, store = ov({"import_limit_kw": 10})
    o.controller = SimpleNamespace(fuse_amps=lambda: amps["v"])
    a = A.AutoFix(o)
    a.run()
    a.seen("fuse_inverter")
    a.run()
    assert store["import_limit_kw"] == 32 and a.lines() == []
    amps["v"] = 35.0
    a.run()
    assert store["import_limit_kw"] == 22 and [e["to"] for e in a.lines()] == [22]


def test_fuse_from_the_inverter_never_overrides_the_users_own():
    for own in (25, None):  # typed in, or taken away on purpose
        o, store = ov({"import_limit_kw": own})
        o.controller = SimpleNamespace(fuse_amps=lambda: 50.0)
        a = A.AutoFix(o)
        a.run()
        assert store["import_limit_kw"] == own
    o, store = ov({"import_limit_kw": 10, "fuse_ok": True})  # 10 kW confirmed as right
    o.controller = SimpleNamespace(fuse_amps=lambda: 50.0)
    A.AutoFix(o).run()
    assert store["import_limit_kw"] == 10

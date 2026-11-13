"""Things that run cheaply: small batteries and machines, after the house battery and the cars."""

import asyncio
from datetime import datetime, timedelta

from energy_pilot.engine import Hour
from energy_pilot.things import Things, find

T0 = datetime(2026, 6, 1, 0, 0)


def hours(prices, sun=None):
    return [Hour(T0 + timedelta(hours=i), p, 0.05, 0.5, (sun or {}).get(i, 0.0)) for i, p in enumerate(prices)]


class FakeHA:
    def __init__(self, states):
        self.states, self.calls = states, []

    async def call_service(self, domain, service, data, response=False):
        self.calls.append((domain, service, dict(data)))
        if service in ("turn_on", "turn_off") and (e := data.get("entity_id")) in self.states:
            self.states[e]["state"] = "on" if service == "turn_on" else "off"


def test_battery_gets_cheapest_hours_and_leftover_sun():
    th = Things({})
    st = {"things": [{"id": "m", "kind": "battery", "switch": "switch.m", "kwh": 0.5, "kw": 0.25, "mode": "sun_cheap"}]}
    hs = hours([2.0] * 24)
    hs[3] = Hour(hs[3].start, 0.5, 0.05, 0.5, 0)  # cheap at night
    left = {hs[12].start: 1.0, hs[13].start: 1.0}  # sun the plan would sell
    p = th.plan(st, hs, T0, left, {}, None)[0]
    assert p["hours"] == [hs[12].start.isoformat(), hs[13].start.isoformat()] and p["sun"]  # sun is worth 0.05 < 0.5


def test_sun_only_waits_without_sun_and_fuse_is_kept():
    th = Things({})
    st = {"things": [{"id": "m", "kind": "battery", "switch": "switch.m", "kwh": 0.5, "kw": 0.5, "mode": "sun"}]}
    hs = hours([1.0] * 24)
    assert th.plan(st, hs, T0, {}, {}, None)[0]["hours"] == []
    st["things"][0]["mode"] = "cheap"
    load = {h.start: 10.5 for h in hs[:23]}  # the cars fill the fuse in all but the last hour
    assert th.plan(st, hs, T0, {}, load, 11.0)[0]["hours"] == [hs[23].start.isoformat()]


def test_battery_switched_in_its_hour_and_full_when_charger_rests():
    th = Things({})
    st = {"things": [{"id": "m", "kind": "battery", "switch": "switch.m", "power": "sensor.m", "kwh": 0.2, "kw": 0.2, "mode": "cheap"}]}
    hs = hours([1.0] * 24)
    hs[2] = Hour(hs[2].start, 0.1, 0.05, 0.5, 0)
    th.plan(st, hs, T0, {}, {}, None)
    ha = FakeHA({"switch.m": {"state": "off"}, "sensor.m": {"state": "80"}})
    now = T0 + timedelta(hours=2, minutes=1)
    asyncio.run(th.tick(ha, st, now, 0.1, 0.05, 100))
    assert ha.states["switch.m"]["state"] == "on"
    for i in range(1, 60):  # 30 min: 10 charging, then the charger takes nothing
        ha.states["sensor.m"]["state"] = "80" if i < 20 else "1"
        asyncio.run(th.tick(ha, st, now + timedelta(seconds=30 * i), 0.1, 0.05, 100))
    assert th.full_today("m", now) and ha.states["switch.m"]["state"] == "off"
    assert th.st("m")["runs"][-1]["kwh"] > 0


def test_machine_started_once_ready_and_never_switched_off():
    th = Things({})
    st = {"things": [{"id": "d", "kind": "machine", "start": "button.d_start", "power": "sensor.d", "mode": "cheap", "kwh": 1.0, "kw": 1.0}]}
    hs = hours([2.0] * 24)
    hs[5] = Hour(hs[5].start, 0.2, 0.05, 0.5, 0)
    assert th.plan(st, hs, T0, {}, {}, None)[0]["start"] is None  # not ready: nothing planned
    th.arm("d", True)
    p = th.plan(st, hs, T0, {}, {}, None)[0]
    assert p["start"] == hs[5].start.isoformat()
    ha = FakeHA({"button.d_start": {"state": "unknown"}, "sensor.d": {"state": "0"}})
    asyncio.run(th.tick(ha, st, hs[5].start, 0.2, 0.05, 100))
    assert ("button", "press", {"entity_id": "button.d_start"}) in ha.calls
    t = hs[5].start
    for i in range(1, 200):  # runs an hour, then rests: done
        ha.states["sensor.d"]["state"] = "1500" if i < 120 else "0"
        asyncio.run(th.tick(ha, st, t + timedelta(seconds=30 * i), 0.2, 0.05, 100))
    assert not any(c[1] == "turn_off" for c in ha.calls)
    s = th.st("d")
    assert not s["armed"] and not s["running"] and s["last"]["kwh"] > 1


def test_learns_from_three_runs():
    th = Things({})
    th.st("x")["runs"] = [{"kwh": 0.6, "min": 100}, {"kwh": 0.7, "min": 110}, {"kwh": 0.8, "min": 120}]
    kwh, minutes, _ = th.need({"id": "x", "kind": "battery", "kwh": 2})
    assert (kwh, minutes) == (0.7, 110)


def test_find_offers_machines_and_mowers_not_phones():
    reg = [{"entity_id": "button.bosch_dishwasher_start", "device_id": "d1", "platform": "home_connect"},
           {"entity_id": "sensor.bosch_dishwasher_power", "device_id": "d1", "platform": "home_connect"},
           {"entity_id": "switch.shelly_mower", "device_id": "d2", "platform": "shelly"},
           {"entity_id": "sensor.pixel_battery", "device_id": "d3", "platform": "mobile_app"},
           {"entity_id": "switch.stue_lys", "device_id": "d4", "platform": "hue"}]
    devs = {"d1": {"name": "Opvaskemaskine"}, "d2": {"name": "Robotplæneklipper"}, "d3": {"name": "Pixel 8"}, "d4": {"name": "Stue lys"}}
    states = {e["entity_id"]: {"state": "on", "attributes": {"device_class": "power"} if "power" in e["entity_id"] else {}} for e in reg}
    out = find(reg, devs, states, set(), [])
    assert [(c["name"], c["kind"], c["icon"]) for c in out] == [("Opvaskemaskine", "machine", "dish"), ("Robotplæneklipper", "battery", "mower")]
    assert out[0]["start"] == "button.bosch_dishwasher_start"
    assert find(reg, devs, states, {"switch.shelly_mower"}, ["d1"]) == []


def test_find_skips_room_sensors_and_robot_mowers():
    reg = [{"entity_id": "button.vaskerum_fp300_restart_device", "device_id": "r", "platform": "zha"},
           {"entity_id": "lawn_mower.garden", "device_id": "g", "platform": "husqvarna"},
           {"entity_id": "switch.garden_advanced_mode", "device_id": "g", "platform": "husqvarna"}]
    devs = {"r": {"name": "Vaskerum_fp300"}, "g": {"name": "Græsslåmaskine"}}
    states = {e["entity_id"]: {"state": "on", "attributes": {}} for e in reg}
    assert find(reg, devs, states, set(), []) == []

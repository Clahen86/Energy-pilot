"""A water heater: on, resting only in the dearest hours (at most 4 a day, never in sun) - found by itself."""

import asyncio
from datetime import datetime, timedelta

from energy_pilot.engine import Hour
from energy_pilot.things import Things, find

T0 = datetime(2026, 11, 22, 0, 0)
ST = {"things": [{"id": "h", "kind": "heater", "switch": "switch.vvb"}]}


class FakeHA:
    def __init__(self, states):
        self.states, self.calls = states, []

    async def call_service(self, domain, service, data, response=False):
        self.calls.append((domain, service, dict(data)))
        if service in ("turn_on", "turn_off") and (e := data.get("entity_id")) in self.states:
            self.states[e]["state"] = "on" if service == "turn_on" else "off"


def _day():
    prices = [1.0] * 24
    for h, p in ((17, 3.0), (18, 3.2), (19, 3.1), (20, 2.9), (21, 2.8), (8, 2.5)):
        prices[h] = p
    return [Hour(T0 + timedelta(hours=i), p, 0.05, 0.5, 0.0) for i, p in enumerate(prices)]


def test_rests_in_the_four_dearest_hours_only():
    th = Things({})
    p = th.plan(ST, _day(), T0, {}, {}, None)[0]
    assert [datetime.fromisoformat(x).hour for x in p["off"]] == [17, 18, 19, 20]
    flat = [Hour(T0 + timedelta(hours=i), 1.0, 0.05, 0.5, 0.0) for i in range(24)]
    assert th.plan(ST, flat, T0, {}, {}, None)[0]["off"] == []  # no clearly dear hours: always on


def test_never_rests_when_there_is_sun_to_spare():
    th = Things({})
    hs = _day()
    p = th.plan(ST, hs, T0, {hs[17].start: 1.0}, {}, None)[0]
    assert 17 not in [datetime.fromisoformat(x).hour for x in p["off"]]


def test_switched_off_in_the_dear_hour_and_a_hand_turned_on_heater_stays_on():
    th = Things({})
    th.plan(ST, _day(), T0, {}, {}, None)
    ha = FakeHA({"switch.vvb": {"state": "on"}})
    asyncio.run(th.tick(ha, ST, T0 + timedelta(hours=17, minutes=1), 3.0, 0.05, 100))
    assert ha.states["switch.vvb"]["state"] == "off"
    ha.states["switch.vvb"]["state"] = "on"  # someone wants hot water now
    asyncio.run(th.tick(ha, ST, T0 + timedelta(hours=17, minutes=10), 3.0, 0.05, 100))
    assert ha.states["switch.vvb"]["state"] == "on"
    asyncio.run(th.tick(ha, ST, T0 + timedelta(hours=21, minutes=1), 2.8, 0.05, 100))
    assert ha.states["switch.vvb"]["state"] == "on"  # back on after its hours
    assert th.view(ST, T0 + timedelta(hours=12))[0]["status"] == "heat"


def test_found_by_itself():
    reg = [{"entity_id": "switch.varmtvandsbeholder", "device_id": "d1", "platform": "shelly"}]
    states = {"switch.varmtvandsbeholder": {"state": "on", "attributes": {}}}
    out = find(reg, {"d1": {"name": "Varmtvandsbeholder"}}, states, set(), [])
    assert [(c["kind"], c["icon"]) for c in out] == [("heater", "heater")]

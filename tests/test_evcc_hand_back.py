"""evcc runs its own plans ("smart"): when Energy Pilot lets go of the car it gets them back, instead of staying at the
"off" or "now" Energy Pilot left it at."""

import asyncio

from energy_pilot import adapters
from energy_pilot.control import Controller

MODE = "select.evcc_garage_mode"


class HA:
    def __init__(self, options):
        self.states = {MODE: {"state": "off", "attributes": {"options": options}}}
        self.config = {}


class OV:
    def __init__(self, mode):
        self.settings = {"control": {"car": mode}}

    def role(self, k):
        return None

    def save(self, d):
        self.settings.update(d)


def _ctl(mode="control", options=("off", "smart", "now")):
    c = Controller(HA(list(options)), OV(mode), None)
    c.platforms = {"car": "evcc_intg"}
    c.entities = {"car": [MODE, "select.evcc_garage_vehicle_name"], "battery": []}
    c.blocked = lambda part: None
    c.intents = lambda: {}  # no battery to put back here
    sent = []

    async def send(calls, force=False):
        sent.extend(calls)

    c._send = send
    return c, sent


def test_evcc_gets_its_own_planning_back():
    assert adapters.charger_hand_back("evcc_intg", [MODE]) == [
        {"domain": "select", "service": "select_option", "data": {"entity_id": MODE, "option": "re:^(smart|pv)$"}}]
    assert adapters.charger_hand_back("easee", ["switch.easee_x"]) == []  # most chargers are left as they are


def test_leaving_control_hands_evcc_back_to_smart():
    c, sent = _ctl()
    asyncio.run(c.hand_back("car"))
    assert sent == [{"domain": "select", "service": "select_option", "data": {"entity_id": MODE, "option": "smart"}}]


def test_an_older_evcc_gets_pv():
    c, sent = _ctl(options=("off", "pv", "minpv", "now"))
    asyncio.run(c.hand_back("car"))
    assert sent[0]["data"]["option"] == "pv"


def test_in_shadow_nothing_is_sent():
    c, sent = _ctl(mode="shadow")
    asyncio.run(c.hand_back("car"))
    assert sent == []


def test_stop_all_hands_evcc_back_too():
    c, sent = _ctl()
    asyncio.run(c.release())
    assert {"domain": "select", "service": "select_option", "data": {"entity_id": MODE, "option": "smart"}} in sent
    assert c.ov.settings["control"]["car"] == "shadow"

"""device_id stays in the action's data (Easee wants text, not a list); the sell stop steps aside while the battery sells."""

import asyncio

from energy_pilot import curtail
from energy_pilot.ha import HomeAssistant as HAClient


def test_device_id_stays_in_data():
    c = HAClient.__new__(HAClient)
    sent = {}

    async def command(msg, timeout=0):
        sent.update(msg)
    c.command = command
    asyncio.run(c.call_service("easee", "set_charger_dynamic_limit", {"device_id": "abc", "current": 16}))
    assert sent["service_data"] == {"device_id": "abc", "current": 16} and "target" not in sent
    asyncio.run(c.call_service("select", "select_option", {"entity_id": "select.x", "option": "A"}))
    assert sent["target"] == {"entity_id": "select.x"}


class Ctl:
    def __init__(self, intent=None, testing=()):
        self.last = {"battery": {"intent": intent}} if intent else {}
        self.testing = set(testing)

    def mode(self, part):
        return "control"


def run(ctl):
    c = curtail.Curtail.__new__(curtail.Curtail)
    calls = []

    async def _set(e, v):
        calls.append((e, v))
        return True
    saves = {}
    c.ha = type("H", (), {"states": {"select.deye_limit_control_mode": {"state": "Selling first"}}})()
    c.ov = type("O", (), {"settings": {"curtail": {"on": True, "entity": "select.deye_limit_control_mode", "value": "Zero export to CT", "below": 0.1}},
                          "save": lambda self, d: saves.update(d)})()
    c.ctl, c.testing, c.last = ctl, False, {}
    c._set = _set
    c.sell_now = lambda: 0.0
    asyncio.run(c.tick())
    return calls


def test_sell_stop_steps_aside_while_battery_sells_or_tests():
    assert run(Ctl("export")) == []
    assert run(Ctl("hold", testing=["battery"])) == []
    assert run(Ctl("hold")) == [("select.deye_limit_control_mode", "Zero export to CT")]

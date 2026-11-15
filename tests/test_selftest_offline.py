import asyncio
import time

from energy_pilot.selftest import SelfTest


class Ctl:
    def __init__(self, states):
        self.ha = type("HA", (), {"states": states})()
        self.sent = []

    async def _send(self, calls, force=False):
        for c in calls:
            self.sent.append(c)
            e = c["data"]["entity_id"]
            if self.ha.states.get(e, {}).get("state") not in ("unavailable", None):
                self.ha.states[e] = {"state": str(c["data"].get("option", c["data"].get("value")))}
        return "ok"

    def _matches(self, c):
        e = c["data"]["entity_id"]
        return str(self.ha.states.get(e, {}).get("state")) == str(c["data"].get("option", c["data"].get("value")))


class Ov:
    def __init__(self):
        self.settings = {}

    def save(self, d):
        self.settings.update(d)


def test_offline_settings_go_back_when_online_again():
    states = {"select.evcc_max_current": {"state": "unavailable"}, "number.evcc_limit_soc": {"state": "unavailable"}}
    ctl, ov = Ctl(states), Ov()
    t = SelfTest(ctl, ov)
    ov.settings["selftest"] = {"saved": {"select.evcc_max_current": "16", "number.evcc_limit_soc": "80"}}
    asyncio.run(t._restore())
    r = ov.settings["selftest"]["restored"]
    assert r["pending"] == {"select.evcc_max_current": "16", "number.evcc_limit_soc": "80"}
    asyncio.run(t.retry_pending())  # still offline: nothing sent
    assert len(ctl.sent) == 2
    states["select.evcc_max_current"] = {"state": "7"}
    states["number.evcc_limit_soc"] = {"state": "50"}
    asyncio.run(t.retry_pending())
    assert states["select.evcc_max_current"]["state"] == "16" and states["number.evcc_limit_soc"]["state"] == "80"
    r = ov.settings["selftest"]["restored"]
    assert r["pending"] is None and r["left"] == [] and r["result"] == "ok"


def test_pending_dropped_after_two_days():
    ctl, ov = Ctl({"select.x": {"state": "7"}}), Ov()
    t = SelfTest(ctl, ov)
    ov.settings["selftest"] = {"restored": {"pending": {"select.x": "16"}, "pending_since": time.time() - 3 * 86400}}
    asyncio.run(t.retry_pending())
    assert ctl.sent == [] and ov.settings["selftest"]["restored"]["pending"] is None

"""Ready to take over? and "Try control for 24 hours" - back to shadow by itself, also after a restart."""

import asyncio
from datetime import datetime
import time
from types import SimpleNamespace

from energy_pilot import trial

NOW = datetime(2026, 11, 27, 12)


class Ctl:
    def __init__(self, ov):
        self.ov, self.handed = ov, []

    def bat_parts(self):
        return []

    def blocked(self, p):
        return None

    def mode(self, p):
        return (self.ov.settings.get("control") or {}).get(p) or "shadow"

    def set_mode(self, p, m):
        self.ov.settings.setdefault("control", {})[p] = m

    async def hand_back(self, p):
        self.handed.append(p)


def _ov(**s):
    ov = SimpleNamespace(settings={"first_seen": "2026-11-20", **s}, engine=None)
    ov.save = lambda ch: ov.settings.update(ch)
    ov.controller = Ctl(ov)
    return ov


def test_asked_after_three_days_with_the_test_passed():
    assert trial.view(_ov(), "ok", NOW)["ask"]
    assert trial.view(_ov(), "failed", NOW) is None
    assert trial.view(_ov(first_seen="2026-11-26"), "ok", NOW) is None
    assert trial.view(_ov(ready_no=time.time()), "ok", NOW) is None  # "Not now": a week's rest


def test_a_trial_controls_for_a_day_then_goes_back_to_shadow():
    ov = _ov()
    assert trial.start(ov, NOW) and ov.controller.mode("battery") == "control"
    assert trial.view(ov, "ok", NOW)["running"]
    ov.settings["trial"]["until"] = time.time() - 1  # a day later (or after a restart: it's kept in the settings)
    asyncio.run(trial.tick(ov, NOW))
    assert ov.controller.mode("battery") == "shadow" and ov.controller.handed == ["battery"]
    assert trial.view(ov, "ok", NOW)["done"]

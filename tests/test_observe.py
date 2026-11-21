"""Daily control as a test (control._observe): an order the battery followed for a while counts, once a day."""
import time
from types import SimpleNamespace

from energy_pilot.control import Controller


def _ctl(flow, intent="charge", target=90):
    sent, saved = [], {}
    ctl = Controller.__new__(Controller)
    ov = SimpleNamespace(settings={"control": {"battery": "control"}}, flow=lambda: flow,
                         telemetry=SimpleNamespace(event=lambda k, p: sent.append((k, p))))
    ov.save = lambda d: (saved.update(d), ov.settings.update(d))
    ctl.ov = ov
    ctl.last = {"battery": {"intent": intent, "result": "ok", "ctx": {"target": target}}}
    ctl.blocked = lambda part: None
    ctl.profile_key = lambda part="battery": "growatt"
    ctl.model = "SPH"
    return ctl, sent


def test_charging_seen_three_times_counts_once():
    ctl, sent = _ctl({"battery": 2000, "grid": 2500, "soc": 40})
    ctl._observe()
    ctl._obs["since"] = time.time() - 600  # it has had time to react
    for _ in range(5):
        ctl._observe()
    assert sent == [("observed", {"profile": "growatt", "model": "SPH", "intent": "charge"})]


def test_not_counted_when_it_does_otherwise_or_is_full():
    ctl, sent = _ctl({"battery": -1500, "grid": 0, "soc": 40})
    ctl._observe()
    ctl._obs["since"] = time.time() - 600
    for _ in range(5):
        ctl._observe()
    assert sent == []
    ctl, sent = _ctl({"battery": 0, "grid": 300, "soc": 89}, target=90)
    for _ in range(5):
        ctl._observe()
    assert sent == []

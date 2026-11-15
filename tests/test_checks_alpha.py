from types import SimpleNamespace

from energy_pilot.checks import alpha_period


def _eng(log):
    return SimpleNamespace(ov=SimpleNamespace(controller=SimpleNamespace(log={"battery": log})))


def test_alpha_period_shown_when_last_send_refused():
    err = "alphaess.setbatterycharge: Cannot add charge period 1 to a weekly schedule with no existing period"
    assert alpha_period(_eng([{"mode": "control", "result": "failed: x", "error": err}]))[0]["key"] == "alpha_period"


def test_alpha_period_gone_once_it_works():
    assert alpha_period(_eng([{"mode": "control", "result": "ok"},
                              {"mode": "control", "result": "failed", "error": "no existing period"}])) == []
    assert alpha_period(_eng([{"mode": "control", "result": "failed", "error": "timeout"}])) == []

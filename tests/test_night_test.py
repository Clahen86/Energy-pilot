"""The test by itself at night (selftest.night_check): only with the user's yes, at night, in shadow, once per profile."""
from datetime import datetime
from types import SimpleNamespace

from energy_pilot.selftest import SelfTest


def _st(settings, mode="shadow"):
    st = SelfTest.__new__(SelfTest)
    ov = SimpleNamespace(settings=settings)
    ov.save = lambda d: ov.settings.update(d)
    st.ov = ov
    st.ctl = SimpleNamespace(profile_key=lambda part="battery": "growatt", mode=lambda part: mode)
    st.started = []
    st.status = lambda: {"running": False}
    st.can = lambda: {"battery": None}
    st.start = lambda parts: st.started.append(parts) or True
    return st


NIGHT, DAY = datetime(2026, 11, 22, 3, 0), datetime(2026, 11, 22, 14, 0)


def test_never_without_a_yes():
    st = _st({})
    assert not st.night_check(NIGHT) and st.started == []


def test_at_night_in_shadow_once():
    st = _st({"auto_test": True})
    assert not st.night_check(DAY)
    assert st.night_check(NIGHT) and st.started == [["battery"]]
    st.ov.settings["selftest"] = {"results": [{"part": "battery", "result": "ok"}]}
    st.night_check(NIGHT)  # the test ended: what it found is kept
    assert st.ov.settings["auto_tested"]["ok"] is True
    assert not st.night_check(NIGHT) and len(st.started) == 1  # passed: not again


def test_not_while_controlling():
    st = _st({"auto_test": True}, mode="control")
    assert not st.night_check(NIGHT) and st.started == []

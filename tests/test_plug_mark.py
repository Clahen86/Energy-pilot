"""The session meter at plug-in: a KEBA keeps last time's number until the car starts charging."""

from energy_pilot import chargers


def _st(session, plug="on", s_changed="2026-11-16T22:17:09+00:00", p_changed="2026-11-16T22:17:08+00:00"):
    return {"sensor.s": {"state": str(session), "last_changed": s_changed},
            "binary_sensor.p": {"state": plug, "last_changed": p_changed}}


def test_old_number_after_restart_is_zero_with_mark():
    st = _st(19.84)  # a restart gave both a new last_changed
    assert chargers.session(st, "sensor.s", "binary_sensor.p") == 19.84  # without the mark: wrong
    assert chargers.session(st, "sensor.s", "binary_sensor.p", 19.84) == 0
    assert chargers.session(_st(2.5), "sensor.s", "binary_sensor.p", 19.84) == 2.5  # a new session from 0
    assert chargers.session(_st(25.0), "sensor.s", "binary_sensor.p", 19.84) == 5.16  # a meter that counts on
    assert chargers.session(_st(19.84, plug="off"), "sensor.s", "binary_sensor.p", 19.84) == 19.84

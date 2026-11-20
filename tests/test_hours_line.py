"""The daily hourly line (telemetry.hours_line): yesterday as the review saw it, sent once."""
from types import SimpleNamespace

from energy_pilot.telemetry import Telemetry


def _tel(reports, sent=None):
    t = Telemetry.__new__(Telemetry)
    eng = SimpleNamespace(learning=SimpleNamespace(state={"reports": reports}))
    t.ov = SimpleNamespace(engine=eng, settings={"hours_sent_day": sent})
    return t


def test_yesterday_hour_by_hour():
    rep = {"day": "2026-11-20", "hours": [{"h": 0, "house": [0.4, 0.37], "sun": [0, 0.0], "soc": [10, 10], "price": 1.9},
                                           {"h": 1, "house": [None, 0.36], "sun": [None, 0.0], "soc": [None, 10]}]}
    line = _tel([rep]).hours_line()
    assert line["day"] == "2026-11-20"
    assert line["hours"][0] == {"h": 0, "house": [0.4, 0.37], "sun": [0, 0.0], "soc": [10, 10], "price": 1.9}
    assert line["hours"][1]["price"] is None
    assert set(line) == {"day", "hours"}  # nothing else: no names, no entities


def test_sent_once_and_nothing_without_a_review():
    rep = {"day": "2026-11-20", "hours": [{"h": 0}]}
    assert _tel([rep], sent="2026-11-20").hours_line() is None
    assert _tel([]).hours_line() is None

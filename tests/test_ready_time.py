from datetime import datetime
from zoneinfo import ZoneInfo

from energy_pilot.engine import ready_time

NOW = datetime(2026, 11, 15, 21, 0, tzinfo=ZoneInfo("Europe/Copenhagen"))


def test_ready_time_formats():
    assert ready_time("07:00", NOW) == (7, 0)
    assert ready_time("07:30:00", NOW) == (7, 30)
    assert ready_time("7.15", NOW) == (7, 15)
    assert ready_time("7:00 AM", NOW) == (7, 0)
    assert ready_time("6:45 pm", NOW) == (18, 45)
    assert ready_time("12:00 AM", NOW) == (0, 0)
    assert ready_time("2026-11-16T06:00:00+00:00", NOW) == (7, 0)
    assert ready_time("2026-11-16 07:00:00", NOW) == (7, 0)


def test_ready_time_unset_or_bad():
    for v in (None, "", "00:00:00", "unknown", "unavailable", "soon", "25:00", "07"):
        assert ready_time(v, NOW) is None

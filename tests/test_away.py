"""Nobody home for a day: the plan counts on the house's standby use - back to normal when someone is home."""

from datetime import datetime, timedelta, timezone

from energy_pilot.away import is_away, standby

NOW = datetime(2026, 7, 10, 12, tzinfo=timezone.utc)


def _p(state, hours_ago):
    return {"state": state, "last_changed": (NOW - timedelta(hours=hours_ago)).isoformat()}


def test_away_after_a_day_when_everyone_has_left():
    assert is_away({"person.a": _p("not_home", 30), "person.b": _p("Work", 26)}, NOW)
    assert not is_away({"person.a": _p("not_home", 30), "person.b": _p("not_home", 5)}, NOW)  # the last left 5 h ago


def test_someone_home_or_nobody_known_is_never_away():
    assert not is_away({"person.a": _p("not_home", 30), "person.b": _p("home", 40)}, NOW)
    assert not is_away({}, NOW)
    assert not is_away({"person.a": _p("unknown", 99)}, NOW)  # no tracker
    assert is_away({"person.a": _p("not_home", 30), "person.guest": _p("unknown", 1)}, NOW)  # the guest without one is left out


def test_standby_is_the_quietest_hour_ahead():
    assert standby([0.9, 0.3, 0.25, 1.4]) == 0.25
    assert standby([]) is None

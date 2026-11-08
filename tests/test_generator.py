"""Off-grid: the generator runs when the battery needs it - not when the sun will do it."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from energy_pilot.generator import GenSettings, decide

TZ = ZoneInfo("America/Toronto")
NOW = datetime(2026, 12, 1, 14, tzinfo=TZ)


def hours(n, house, sun_by_hour=None):
    return [(NOW + timedelta(hours=i), house, (sun_by_hour or {}).get((NOW + timedelta(hours=i)).hour, 0.0)) for i in range(n)]


S = GenSettings(capacity_kwh=30, efficiency=1.0, reserve_soc=30, emergency_soc=20, stop_soc=90, charge_kw=5, min_run_h=2,
                quiet=frozenset(range(22, 24)) | frozenset(range(0, 7)))


def test_emergency_always_starts():
    d = decide(NOW.replace(hour=2), 18, False, None, hours(24, 1.0), S)
    assert d["run"] and d["why"] == "emergency"


def test_sun_coming_means_no_generator():
    sunny = {h: 4.0 for h in range(9, 16)}
    d = decide(NOW, 60, False, None, hours(48, 0.4, sunny), S)
    assert not d["run"] and d["why"] == "not_needed" and d["low_at"] is None


def test_starts_in_time_before_the_reserve_and_not_too_early():
    # 0.5 kWh/h, no sun: from 50 % (15 kWh) the reserve (9 kWh) is reached in 12 hours
    d = decide(NOW, 50, False, None, hours(48, 0.5), S)
    assert d["low_at"] is not None
    assert not d["run"] and d["why"] == "later" and d["start_at"]  # not yet - but it knows when
    later = datetime.fromisoformat(d["start_at"])
    d2 = decide(later, 50 - (later - NOW).total_seconds() / 3600 * 0.5 / 30 * 100, False, None,
                [(later + timedelta(hours=i), 0.5, 0.0) for i in range(48)], S)
    assert d2["run"]


def test_runs_its_minimum_and_stops_when_full_or_sun_carries():
    assert decide(NOW, 95, True, NOW - timedelta(hours=1), hours(24, 1.0), S)["why"] == "min_run"
    assert decide(NOW, 92, True, NOW - timedelta(hours=3), hours(24, 1.0), S)["why"] == "full"
    sunny = {h: 5.0 for h in range(8, 17)}
    d = decide(NOW, 70, True, NOW - timedelta(hours=3), hours(48, 0.6, sunny), S)
    assert not d["run"] and d["why"] == "sun_carries"


def test_quiet_hours_wait_if_the_battery_lasts():
    night = NOW.replace(hour=23)
    # plenty left: the reserve is reached long after the quiet hours end
    d = decide(night, 60, False, None, [(night + timedelta(hours=i), 0.5, 0.0) for i in range(48)], S)
    assert not d["run"]

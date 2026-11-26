"""A power tariff that counts only some hours (Swedish high-tariff hours: weekdays 07-20, November-March)."""

from datetime import datetime, timedelta, timezone

from energy_pilot.powertariff import MonthPeak, counts

W = {"power_tariff_hours": {"days": "weekdays", "from": "07:00", "to": "20:00", "months": [11, 12, 1, 2, 3]}}


def test_counts_only_weekday_daytime_in_winter():
    assert counts(W, datetime(2026, 11, 26, 9))  # Thursday morning
    assert not counts(W, datetime(2026, 11, 26, 21))  # evening
    assert not counts(W, datetime(2026, 11, 28, 9))  # Saturday
    assert not counts(W, datetime(2026, 7, 8, 9))  # summer
    assert counts({}, datetime(2026, 11, 28, 3))  # nothing set: every hour


def test_free_hours_never_raise_the_peak():
    state = {}
    mp = MonthPeak(state)
    t = datetime(2026, 11, 26, 22, tzinfo=timezone.utc)
    for i in range(130):  # two hours charging at 6 kW in the night
        now = t + timedelta(minutes=i)
        mp.see(now, 6000, 60, counts(W, now))
    assert mp.level() is None
    t = datetime(2026, 11, 27, 9, tzinfo=timezone.utc)
    for i in range(70):
        now = t + timedelta(minutes=i)
        mp.see(now, 1000, 60, counts(W, now))
    assert mp.level() == 1.0

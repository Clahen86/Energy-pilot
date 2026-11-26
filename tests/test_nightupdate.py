"""Updating at night: in a quiet moment between midnight and six, once a version has been out a day."""

from datetime import datetime, timedelta, timezone

from energy_pilot.nightupdate import due, quiet

N = datetime(2026, 11, 27, 2, 10, tzinfo=timezone.utc)
DAY_AGO = (N - timedelta(hours=25)).timestamp()


def steps(*acts):
    t0 = N.replace(minute=0)
    return [{"t": (t0 + timedelta(minutes=15 * i)).isoformat(), "action": a} for i, a in enumerate(acts)]


def test_updates_in_a_quiet_night_moment():
    assert due(N, "0.113.1", "0.113.2", DAY_AGO, steps("hold", "hold", "discharge", "hold"))


def test_waits_while_charging_selling_or_the_car_charges():
    assert not quiet(steps("charge_grid", "hold", "hold"), N)  # the slot running now charges
    assert not quiet(steps("hold", "export"), N)  # selling within 20 minutes
    assert not due(N, "0.113.1", "0.113.2", DAY_AGO, steps("hold"), ev_w=7000)


def test_not_by_day_not_too_new_not_off_and_not_dev():
    assert not due(N.replace(hour=14), "0.113.1", "0.113.2", DAY_AGO, [])
    assert not due(N, "0.113.1", "0.113.2", N.timestamp() - 3600, [])  # out only an hour
    assert not due(N, "0.113.1", "0.113.2", DAY_AGO, [], enabled=False)
    assert not due(N, "0.113.1", "0.113.2", DAY_AGO, [], ha_auto=True)  # Home Assistant updates it itself
    assert not due(N, "dev", "0.113.2", DAY_AGO, [])
    assert not due(N, "0.113.2", "0.113.2", DAY_AGO, [])

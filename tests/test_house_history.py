"""The house's own history, kept by Energy Pilot when Home Assistant keeps no statistics."""

from datetime import datetime, timedelta

from energy_pilot.househist import HouseHistory


def test_keeps_hour_means_and_prunes():
    st = {}
    h = HouseHistory(st)
    t0 = datetime(2026, 1, 1, 0, 0)
    for i in range(120 * 3 + 1):  # three whole hours, then one round into the fourth
        h.see(t0 + timedelta(seconds=30 * i), 1500.0)
    assert len(st["house_hist"]) == 3
    assert h.rows()[0] == (t0, 1.5)
    for i in range(121):  # a whole hour 61 days later: the old hours are dropped
        h.see(t0 + timedelta(days=61, seconds=30 * i), 1000.0)
    assert h.rows() == [(t0 + timedelta(days=61), 1.0)]


def test_half_seen_hour_not_kept():
    st = {}
    h = HouseHistory(st)
    t0 = datetime(2026, 1, 1, 0, 50)
    for i in range(21):  # only the last 10 minutes of the hour
        h.see(t0 + timedelta(seconds=30 * i), 800.0)
    assert st["house_hist"] == {}
    assert h.days() == 0


def _engine(own_days=0, state_class=None, stats_hours=0):
    from types import SimpleNamespace as N

    attrs = {"friendly_name": "House"} | ({"state_class": state_class} if state_class else {})
    hist = HouseHistory({})
    hist.s.update({f"2026-01-01T{h:02d}:00:00": 1.0 for h in range(24)} if own_days else {})
    return N(house_stats_hours=stats_hours, house_hist=hist,
             ov=N(role=lambda r: "sensor.house" if r == "house_power" else None),
             ha=N(states={"sensor.house": {"attributes": attrs}}))


def test_check_offers_own_history():
    from energy_pilot.checks import house_history

    out = house_history(_engine(), {})
    assert out[0]["key"] == "house_no_stats" and out[0]["fix"] == {"own_history": True}
    assert house_history(_engine(state_class="measurement"), {}) == []  # statistics come: a new system, just wait
    assert house_history(_engine(stats_hours=24 * 30), {}) == []
    on = house_history(_engine(own_days=1), {"own_history": True})
    assert on[0]["key"] == "house_own_history" and on[0]["vals"]["d"] == "1"

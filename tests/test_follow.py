from datetime import datetime, timedelta

from energy_pilot.checks import FollowWatch

T0 = datetime(2026, 11, 10, 7, 17)
WANT = {"intent": "normal", "ctx": {"min_soc": 10, "target": 78}}
STUCK = {"battery": 0.0, "grid": 990.0, "house": 1000.0, "pv": 0.0, "soc": 95}
STATES = {"number.growatt_sph_free_mode_discharge_rate": {"state": "0"}, "number.growatt_sph_free_mode_charge_rate": {"state": "100"},
          "number.growatt_sph_load_first_stop_discharge": {"state": "10"}}


def test_a_battery_held_back_is_told_with_the_setting_at_zero():
    w = FollowWatch()
    for m in range(0, 11):
        w.see(T0 + timedelta(minutes=m), "control", WANT, STUCK, STATES, list(STATES))
    (c,) = w.check()
    assert c["key"] == "follow_discharge_why" and c["vals"]["list"] == "growatt_sph_free_mode_discharge_rate = 0"


def test_quiet_when_it_follows_or_in_shadow_or_not_long():
    w = FollowWatch()
    for m in range(0, 5):
        w.see(T0 + timedelta(minutes=m), "control", WANT, STUCK, STATES, list(STATES))
    assert w.check() == []  # not 10 minutes yet
    w.see(T0 + timedelta(minutes=12), "control", WANT, {**STUCK, "battery": -1000.0, "grid": 0.0}, STATES, list(STATES))
    assert w.check() == [] and w.since is None
    s = FollowWatch()
    for m in range(0, 15):
        s.see(T0 + timedelta(minutes=m), "shadow", WANT, STUCK, STATES, list(STATES))
    assert s.check() == []
    low = FollowWatch()  # the battery at its floor may stand still
    for m in range(0, 15):
        low.see(T0 + timedelta(minutes=m), "control", WANT, {**STUCK, "soc": 11}, STATES, list(STATES))
    assert low.check() == []

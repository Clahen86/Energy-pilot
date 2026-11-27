"""The round trip measured on the grid: the jump when the battery starts or stops (Growatt SPH, 2026-11-27)."""

from energy_pilot.acsteps import NEED, AcSteps


def _feed(ac, rows, t0=0.0):
    got = []
    for i, (grid, batt, ev, pv) in enumerate(rows):
        r = ac.see(t0 + i * 30, {"grid": grid, "battery": batt, "ev": ev, "pv": pv})
        if r:
            got.append(r)
    return got


CHARGE_STOP = [(4185, 2990, 0, 0), (4180, 2990, 0, 0), (825, 0, 0, 0), (822, 0, 0, 0)]  # 04:00: grid fell 3360
DISCHARGE_START = [(940, 0, 0, 0), (945, 0, 0, 0), (5, -1120, 0, 0), (0, -1125, 0, 0)]  # 16:30: grid fell 940


def test_a_clean_jump_gives_the_share_each_way():
    ac = AcSteps({})
    (way, share), = _feed(ac, CHARGE_STOP)
    assert way == "in" and abs(share - 1.12) < 0.01
    (way, share), = _feed(AcSteps({}), DISCHARGE_START)
    assert way == "out" and abs(share - 0.84) < 0.01


def test_the_car_or_the_sun_moving_spoils_the_jump():
    rows = [(g, b, ev, pv) for (g, b, _, pv), ev in zip(CHARGE_STOP, (0, 0, 3600, 3600))]
    assert _feed(AcSteps({}), rows) == []
    rows = [(g, b, ev, pv) for (g, b, ev, _), pv in zip(DISCHARGE_START, (0, 0, 800, 800))]
    assert _feed(AcSteps({}), rows) == []


def test_a_ramp_or_a_gap_is_not_a_jump():
    ramp = [(940, 0, 0, 0), (945, 0, 0, 0), (465, -540, 0, 0), (12, -1120, 0, 0)]  # still moving after the jump
    assert _feed(AcSteps({}), ramp) == []
    ac = AcSteps({})
    for i, (g, b, ev, pv) in enumerate(CHARGE_STOP):
        assert ac.see(i * 300, {"grid": g, "battery": b, "ev": ev, "pv": pv}) is None  # samples 5 min apart


def test_charge_to_discharge_and_odd_shares_are_left_out():
    assert _feed(AcSteps({}), [(3000, 2900, 0, 0), (3010, 2900, 0, 0), (0, -100, 0, 0), (5, -100, 0, 0)]) == []
    assert _feed(AcSteps({}), [(800, 0, 0, 0), (810, 0, 0, 0), (5000, 1000, 0, 0), (5010, 1000, 0, 0)]) == []  # 4.2


def test_round_trip_once_enough_jumps_each_way():
    state = {}
    ac = AcSteps(state)
    pp = (0.1138, 0.1269, 20)  # the battery's own kWh per point in and out: 111 % on its own
    for n in range(NEED):
        _feed(ac, CHARGE_STOP, t0=n * 10000)
        assert ac.round_trip(pp) is None or n == NEED - 1
        _feed(ac, DISCHARGE_START, t0=n * 10000 + 5000)
    rt = ac.round_trip(pp)
    assert rt is not None and 0.80 <= rt <= 0.86  # 0.1269 * 0.84 / (0.1138 * 1.12)
    info = ac.info(pp)
    assert info["in"] == info["out"] == NEED and info["round_trip"] == rt
    assert info["in_high"] and info["out_low"] and "in_low" not in info
    assert state["ac_steps"]["in"]  # kept in the learning state, so it survives a restart

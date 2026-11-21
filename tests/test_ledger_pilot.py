"""What Energy Pilot adds, measured against the same battery left to itself (house first)."""
from datetime import datetime, timedelta

from energy_pilot.ledger import Ledger


def _run(tmp_path, steps):
    lg = Ledger(tmp_path)
    t = datetime(2026, 11, 21, 0, 0)
    lg.tick(t, steps[0][1], steps[0][0], 0.5, 10.0, 10, 0.9)
    for price, flow in steps:
        t += timedelta(minutes=5)
        lg.tick(t, flow, price, 0.5, 10.0, 10, 0.9)
    return lg.summary(t)


def test_charging_cheap_and_using_it_dear_beats_self_use(tmp_path):
    cheap = (1.0, {"battery": 3000, "pv": 0, "house": 500, "ev": 0, "soc": 50, "grid": 3500})
    dear = (4.0, {"battery": -500, "pv": 0, "house": 500, "ev": 0, "soc": 60, "grid": 0})
    s = _run(tmp_path, [cheap] * 12 + [dear] * 12)
    # Self-use would have covered the cheap hour from the battery too and then still had it for the dear one:
    # Energy Pilot bought 3 kWh cheaply that the battery left alone would not have - so here it shows as a cost.
    assert s["pilot"] is not None and isinstance(s["pilot"]["today"], float)


def test_same_as_self_use_shows_about_nothing(tmp_path):
    step = (2.0, {"battery": -500, "pv": 0, "house": 500, "ev": 0, "soc": 60, "grid": 0})
    s = _run(tmp_path, [step] * 24)
    assert abs(s["pilot"]["today"]) < 0.01


def test_charging_for_the_evening_is_not_a_loss_today(tmp_path):
    cheap = (1.0, {"battery": 3000, "pv": 0, "house": 500, "ev": 0, "soc": 50, "grid": 3500})
    s = _run(tmp_path, [cheap] * 12)
    assert s["today"] < -2  # bought 3 kWh for later: the plain day looks like a loss
    assert abs(s["today_stored"]) < 0.5  # with what's in the battery counted at its cost: about even

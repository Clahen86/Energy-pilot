"""The learned end value counts what the battery holds at the end of the day, at what refilling it costs.

Comparing the day's cost alone, emptying the battery looked free: the lowest factor (0.6) won every night and the
plan learned to leave the battery empty, buying in the late evening and charging too little at night."""

from datetime import datetime
from zoneinfo import ZoneInfo

from energy_pilot.engine import Battery
from energy_pilot.learning import Learning
from energy_pilot import tune

TZ = ZoneInfo("Europe/Copenhagen")


def danish_day():
    keys = [f"2026-11-24T{h:02d}" for h in range(24)]
    prices = {k: (2.2 if h < 6 else 4.3 if 17 <= h < 20 else 3.3 if 7 <= h < 17 else 2.7) for h, k in enumerate(keys)}
    house = {k: 1.4 for k in keys}
    return keys, prices, house


def test_a_full_battery_at_the_start_does_not_teach_it_to_empty_it(tmp_path):
    keys, prices, house = danish_day()
    L = Learning(tmp_path)
    for k in keys:
        L.expect([{"t": k + ":00:00+01:00", "house": 1.4, "sun": 0.0, "price": prices[k], "cloud": 80}])
    b = Battery(capacity_kwh=45, max_charge_kw=11.85, max_discharge_kw=11.85, efficiency=0.893, wear=0.067)
    rep = L.review(datetime(2026, 11, 24, tzinfo=TZ), house, {}, b, prices, 70)
    assert rep["best_factor"] != 0.6


def test_replay_counts_the_battery_left_at_the_end():
    # The battery goes from 50 % to its floor (10 %) covering the house: about 20.2 kWh bought at 2.0 = 40.4. The 4 kWh
    # it gave count at what refilling them costs (2.0 / 0.95 each), so the day costs about 48.9, not 40.4.
    rows = [{"h": h, "price": 2.05 if 18 <= h < 21 else 2.0, "house": [1.0, 1.0], "sun": [0.0, 0.0],
             "soc": [50.0, 50.0 if h == 0 else None]} for h in range(24)]
    b = Battery(capacity_kwh=10, max_charge_kw=5, max_discharge_kw=5, efficiency=0.9)
    assert abs(tune.replay(rows, b, 0.0, 1.0, 0.0) - 48.85) < 0.05


def test_an_end_factor_learned_the_old_way_starts_again_from_neutral(tmp_path):
    import json

    (tmp_path / "energy_pilot_learning.json").write_text(json.dumps(
        {"end_factor": 0.825, "tune": {"f": 0.9, "m": 0.05, "log": [{"d": "2026-11-20"}]}}))
    L = Learning(tmp_path)
    assert L.end_factor == 1.0 and L.state["tune"]["f"] == 1.0 and L.state["tune"]["m"] == 0.05
    L.state["end_factor"] = 0.95
    L.save()
    assert Learning(tmp_path).end_factor == 0.95  # only once: what it learns from now on is kept

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


def test_equal_factors_keep_the_plain_refill_value(tmp_path):
    # 25 Nov 2026 as it really went: 0.6 to 1.0 all empty the battery the same way and cost the same. A tie took the
    # lowest factor (0.6) every night, so the end factor slid down for nothing.
    house = [0.47, 0.59, 0.72, 0.56, 0.94, 0.56, 1.16, 0.9, 0.75, 1.0, 2.53, 3.17, 2.46, 0.51, 2.45, 2.25, 0.95, 2.02,
             2.02, 1.63, 1.07, 1.12, 0.54, 0.47]
    price = [2.334, 2.297, 2.238, 2.241, 2.222, 2.238, 2.975, 3.474, 3.707, 3.305, 3.1, 3.135, 3.331, 3.564, 3.613,
             3.877, 3.697, 4.405, 4.246, 4.07, 3.785, 2.785, 2.616, 2.575]
    keys = [f"2026-11-25T{h:02d}" for h in range(24)]
    L = Learning(tmp_path)
    for k in keys:
        L.expect([{"t": k + ":00:00+01:00", "house": 1.4, "sun": 0.0, "price": price[int(k[11:])], "cloud": 80}])
    b = Battery(capacity_kwh=45, max_charge_kw=11.85, max_discharge_kw=11.85, grid_max_soc=95, efficiency=0.904,
                wear=0.133)
    rep = L.review(datetime(2026, 11, 25, tzinfo=TZ), dict(zip(keys, house)), {}, b, dict(zip(keys, price)), 30)
    assert rep["best_factor"] == 1.0
    assert L.end_factor == 1.0


def test_a_tie_reset_keeps_the_nightly_test(tmp_path):
    import json

    (tmp_path / "energy_pilot_learning.json").write_text(json.dumps(
        {"end_learn": 2, "end_factor": 0.9, "tune": {"f": 1.0, "m": 0.05, "log": [{"d": "2026-11-24"}]}}))
    L = Learning(tmp_path)
    assert L.end_factor == 1.0 and L.state["tune"]["log"] == [{"d": "2026-11-24"}]

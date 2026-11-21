"""Its own settings, tested every night on its own days: a step only when clearly better, within bounds, and off when off."""
from energy_pilot import tune
from energy_pilot.engine import Battery
from energy_pilot.learning import Learning

B = Battery(capacity_kwh=10, max_charge_kw=3, max_discharge_kw=3, min_soc=10, efficiency=0.9)


def _rows(dear_real=1.6, flat=False):
    rows = []
    for h in range(24):
        price = 1.0 if flat else (0.5 if h < 6 else 3.0 if 17 <= h < 21 else 1.5)
        real = dear_real if 17 <= h < 21 else 0.45 + 0.01 * (h % 7)  # the evening uses more than forecast, every day
        rows.append({"h": h, "house": [0.5, real], "sun": [0.0, 0.0], "soc": [None, 20 if h == 0 else None], "price": price})
    return rows


def _state(n, **kw):
    st = {}
    for i in range(n):
        tune.keep(st, f"2026-11-{i + 1:02d}", _rows(**kw))
    return st


def test_waits_for_enough_days():
    st = _state(4)
    t = tune.nightly(st, B, 0.0, 1.0, 0.0, "2026-11-05")
    assert t["days"] == 4 and (t["f"], t["m"]) == (1.0, 0.0) and not t["log"]


def test_moves_when_clearly_better():
    st = _state(5)
    st["tune"] = {"f": 1.1, "m": 0.0, "log": []}  # a too high end value holds the battery back in the dear evening
    t = tune.nightly(st, B, 0.0, 1.0, 0.0, "2026-11-08")
    assert t["f"] in (1.0, 1.05)  # a step down, or straight back to no adjustment
    assert t["log"][-1]["gain"] > 0 and t["log"][-1]["days"] == 5 and t["log"][-1]["from"] == [1.1, 0.0]


def test_the_best_already_stays():
    st = _state(5)
    t = tune.nightly(st, B, 0.0, 1.0, 0.0, "2026-11-08")
    assert (t["f"], t["m"]) == (1.0, 0.0) and not t["log"] and t["tested"] == "2026-11-08"


def test_nothing_to_win_nothing_moves():
    st = _state(5, flat=True)
    t = tune.nightly(st, B, 0.0, 1.0, 0.0, "2026-11-08")
    assert (t["f"], t["m"]) == (1.0, 0.0) and not t["log"]


def test_stays_within_bounds_night_after_night():
    st = _state(5, dear_real=3.0)
    st["tune"] = {"f": 1.25, "m": 0.3, "log": [{"d": str(i)} for i in range(10)]}  # at the edge already
    for n in range(2):
        tune.nightly(st, B, 0.0, 1.0, 0.0, f"night-{n}")
    t = st["tune"]
    assert tune.F_MIN <= t["f"] <= tune.F_MAX and tune.M_MIN <= t["m"] <= tune.M_MAX
    assert len(t["log"]) <= 10


def test_keeps_two_weeks():
    st = _state(20)
    assert len(st["recent"]) == tune.KEEP_DAYS and min(st["recent"]) == "2026-11-07"


def test_a_stuck_sensor_day_is_left_out():
    st = _state(6)
    st["recent"]["2026-11-03"] = [dict(r, house=[0.5, 0.0]) for r in _rows()]
    assert tune.nightly(st, B, 0.0, 1.0, 0.0, "x")["days"] == 5


def test_plan_uses_it_only_when_on(tmp_path):
    L = Learning(tmp_path)
    L.state.update(end_factor=1.0, house_margin=0.1, tune={"f": 1.1, "m": -0.2, "log": []})
    assert L.plan_settings() == (1.0, 0.1)  # not wired: off
    L.tune_on = lambda: True
    f, m = L.plan_settings()
    assert round(f, 3) == 1.1 and m == 0.0  # the margin never below nothing
    L.tune_on = lambda: False
    assert L.plan_settings() == (1.0, 0.1)
    assert L.summary()["tune"]["on"] is False

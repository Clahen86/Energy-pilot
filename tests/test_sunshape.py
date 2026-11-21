"""The panels' own shape: direction and shade from clear days, the forecast bent per hour - and never anything rash."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from energy_pilot import sunshape as S
from energy_pilot.engine import Battery
from energy_pilot.learning import Learning

TZ = ZoneInfo("Europe/Copenhagen")
LAT, LON = 56.0, 10.0
SOUTH = (180.0, 35.0, False)


def _day(d: str, cand, shade=(), clip=None, cloud=10, fc_cand=SOUTH):
    pos = S._positions(d, list(range(24)), TZ, LAT, LON)
    real, fc = S._curve(pos, cand), S._curve(pos, fc_cand)
    exp, pv = {}, {}
    for h in range(24):
        v = real[h] / 250 * (0.5 if h in shade else 1)
        pv[f"{d}T{h:02d}"] = min(v, clip) if clip else v
        exp[f"{d}T{h:02d}"] = {"cloud": cloud, "sun_raw": fc[h] / 250}
    return exp, pv


def _learn(n, cand, start=date(2026, 11, 1), **kw):
    st = {}
    for i in range(n):
        d = (start + timedelta(days=i)).isoformat()
        exp, pv = _day(d, cand, **kw)
        S.learn_hours(st, exp, pv, d)
        S.add_day(st, S.clear_day(exp, pv, d, TZ, LAT, LON))
    return st


def test_south_west_with_a_shaded_hour():
    p = S.panels(_learn(8, (220.0, 35.0, False), shade=(15,)), TZ, LAT, LON)
    assert p["sure"] and p["az"] == 220 and not p["ew"] and p["shade"] == [[15, 16]]


def test_forecast_set_up_for_the_wrong_way_is_pointed_out():
    p = S.panels(_learn(8, (110.0, 35.0, False), start=date(2026, 4, 1)), TZ, LAT, LON)
    assert p["sure"] and 90 <= p["az"] <= 130 and p["forecast"]["az"] == 180 and p["mismatch"]


def test_east_west_is_told_apart():
    p = S.panels(_learn(8, (90.0, 15.0, True), start=date(2026, 6, 1)), TZ, LAT, LON)
    assert p["sure"] and p["ew"]


def test_still_learning_until_enough_clear_days():
    p = S.panels(_learn(3, SOUTH), TZ, LAT, LON)
    assert p == {"days": 3, "need": S.SURE_DAYS, "sure": False}


def test_cloudy_days_teach_nothing():
    st = _learn(8, (90.0, 35.0, False), cloud=80)
    assert not st.get("clear_days") and not st.get("sun_hour")


def test_factor_neutral_until_seen_and_bounded():
    st = {"sun_hour": {"9": [1.4, 2], "15": [0.1, 9], "16": [3.0, 9]}}
    assert S.factor(st, 9, 0) == 1.0  # seen too few times
    assert S.factor(st, 15, 0) == 0.5 and S.factor(st, 16, 0) == 1.5  # never more than half either way
    assert S.factor(st, 16, 90) == 1.2  # under clouds only part of it
    assert S.factor(st, None, 0) == 1.0


def test_clipped_top_is_not_taken_for_the_panels():
    st = _learn(8, SOUTH, start=date(2026, 6, 1), clip=2.0)
    assert all(abs(f - 1) < 0.05 for f, _ in st["sun_hour"].values())
    p = S.panels(st, TZ, LAT, LON)
    assert p["az"] == 180 and not p.get("mismatch")


def test_review_learns_the_shape_and_sun_uses_it(tmp_path):
    L = Learning(tmp_path)
    L.where = lambda: (LAT, LON)
    for i in range(6):
        d = date(2026, 4, 1) + timedelta(days=i)
        exp, pv = _day(d.isoformat(), (110.0, 35.0, False))
        for k, e in exp.items():
            L.expect([{"t": k + ":00:00+02:00", "house": 0.5, "sun": e["sun_raw"], "price": 1.0, **e}])
        L.review(datetime(d.year, d.month, d.day, tzinfo=TZ), {k: 0.5 for k in exp}, pv, Battery(capacity_kwh=10),
                 {k: 1.0 for k in exp}, 50)
    panels = L.summary()["panels"]
    assert panels["days"] == 6 and panels["sure"] and panels["mismatch"]
    assert L.sun(1.0, 10, 8) > L.sun(1.0, 10, 16)  # east: the morning is lifted, the afternoon lowered
    assert L.sun(1.0, 10) == L.sun(1.0, 10, None)


def test_review_survives_without_a_position(tmp_path):
    L = Learning(tmp_path)  # no where: the hours are still learned, the direction waits
    exp, pv = _day("2026-04-01", SOUTH)
    for k, e in exp.items():
        L.expect([{"t": k + ":00:00+02:00", "house": 0.5, "sun": e["sun_raw"], "price": 1.0, **e}])
    rep = L.review(datetime(2026, 4, 1, tzinfo=TZ), {k: 0.5 for k in exp}, pv, Battery(capacity_kwh=10), {k: 1.0 for k in exp}, 50)
    assert rep is not None and "panels" not in L.state and L.state.get("sun_hour")

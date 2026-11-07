"""The engine: the battery fills when power is cheap or the sun gives too much, and is used when it is dear."""

from datetime import datetime, timedelta

from energy_pilot.engine import Battery, Hour, house_forecast, house_profile, plan_battery, plan_car

T0 = datetime(2026, 11, 7, 0, 0)


def day(prices, sun=None, house=0.8, sell=0.0):
    return [Hour(T0 + timedelta(hours=i), p, sell, house, (sun or [0] * 24)[i]) for i, p in enumerate(prices)]


def test_cheap_night_dear_evening():
    prices = [1.0] * 6 + [2.0] * 11 + [4.0] * 4 + [2.0] * 3  # night cheap, 17-21 dear
    p = plan_battery(day(prices), soc_now=10, b=Battery(capacity_kwh=10))
    actions = [s.action for s in p.steps]
    assert "charge_grid" in actions[:6]
    assert all(a == "discharge" for a in actions[17:21])
    assert p.saving > 0


def test_sun_surplus_is_stored_not_sold_cheaply():
    sun = [0] * 9 + [3, 3, 3, 3, 3] + [0] * 10
    p = plan_battery(day([2.0] * 17 + [3.5] * 7, sun=sun, sell=0.3), soc_now=20, b=Battery(capacity_kwh=10, grid_charge=False))
    assert any(s.action == "charge_sun" for s in p.steps[9:14])
    assert not any(s.action == "charge_grid" for s in p.steps)


def test_flat_price_does_nothing_silly():
    p = plan_battery(day([2.0] * 24), soc_now=50, b=Battery())
    assert not any(s.action == "charge_grid" for s in p.steps)  # charging costs losses, never pays


def test_house_profile_and_car():
    rows = [(T0 - timedelta(days=d, hours=-h), 1.5 if h == 18 else 0.5) for d in range(1, 15) for h in range(24)]
    prof = house_profile(rows, T0)
    fc = house_forecast(prof, [T0 + timedelta(hours=18), T0 + timedelta(hours=3)])
    assert fc[0] > 1.2 and fc[1] < 0.7
    hours = day([3, 3, 1, 1, 2, 2] + [3] * 18)
    chosen = plan_car(hours, need_kwh=14, charger_kw=7, ready=T0 + timedelta(hours=7), now=T0)
    assert [h.hour for h in chosen] == [2, 3]


def test_styles_limits_and_quiet():
    prices = [1.0] * 6 + [2.0] * 11 + [4.0] * 4 + [2.0] * 3
    # Never from the grid
    p = plan_battery(day(prices), soc_now=10, b=Battery(grid_charge=False))
    assert not any(s.action == "charge_grid" for s in p.steps)
    # Quiet at night: no charging 0-6
    p = plan_battery(day(prices), soc_now=10, b=Battery(quiet=frozenset(range(0, 6))))
    assert not any(s.action.startswith("charge") for s in p.steps[:6])
    # A low main fuse: charging may not push the hour over it
    p = plan_battery(day(prices, house=2.5), soc_now=10, b=Battery(import_limit_kw=4.0, max_charge_kw=3))
    assert all(s.grid_kwh <= 4.0 + 1e-6 for s in p.steps if s.action.startswith("charge"))
    # Solar-only car
    hours = day([2] * 24, sun=[0] * 10 + [8, 8] + [0] * 12)
    assert [h.hour for h in plan_car(hours, 14, 7, None, T0, solar_only=True)] == [10, 11]


def test_holidays_and_prices():
    from datetime import date

    from energy_pilot.sources import consumer_price, easter, is_day_off, price_area

    assert easter(2026) == date(2026, 4, 5)
    assert is_day_off(date(2026, 12, 25)) and is_day_off(date(2026, 5, 14))  # Christmas, Ascension
    assert not is_day_off(date(2026, 11, 9))
    assert price_area(55.63, 12.09) == "DK2" and price_area(56.15, 10.2) == "DK1"
    assert consumer_price(1000, 18, {}) > consumer_price(1000, 3, {})  # peak tariff


def test_other_countries():
    from energy_pilot.sources import consumer_price, price_area

    assert price_area(59.33, 18.06, "SE") == "SE3" and price_area(55.6, 13.0, "SE") == "SE4"
    assert price_area(59.9, 10.75, "NO") == "NO1" and price_area(60.39, 5.32, "NO") == "NO5"
    assert price_area(52.5, 13.4, "DE") == "DE-LU"
    assert consumer_price(100, 12, {}, "DE") == round(0.1 * 1.19, 4)  # spot + VAT only, unless told more


def test_tariff_plan():
    from zoneinfo import ZoneInfo

    from energy_pilot.sources import TOU_PRESETS, tou_price, tou_prices

    plan = TOU_PRESETS["sce_tou_d_4_9"]
    assert tou_price(plan, datetime(2026, 11, 9, 17, 0)) == 0.55  # Monday on-peak
    assert tou_price(plan, datetime(2026, 11, 8, 17, 0)) == 0.43  # Sunday mid-peak
    assert tou_price(plan, datetime(2026, 11, 9, 10, 0)) == 0.33
    night = TOU_PRESETS["day_night"]
    assert tou_price(night, datetime(2026, 11, 9, 2, 0)) == 0.20 and tou_price(night, datetime(2026, 11, 9, 12, 0)) == 0.30
    assert len(tou_prices(night, ZoneInfo("America/Los_Angeles"))) == 192


def test_learning_review(tmp_path):
    from zoneinfo import ZoneInfo

    from energy_pilot.learning import Learning

    tz = ZoneInfo("Europe/Copenhagen")
    day = datetime(2026, 11, 6, tzinfo=tz)
    L = Learning(tmp_path)
    keys = [f"2026-11-06T{h:02d}" for h in range(24)]
    prices = {k: (1.0 if h < 6 else 4.0 if 17 <= h < 21 else 2.0) for h, k in enumerate(keys)}
    for h, k in enumerate(keys):
        L.expect([{"t": k + ":00:00+01:00", "house": 0.8, "sun": 1.0 if 10 <= h < 15 else 0.0, "price": prices[k], "cloud": 80}])
    house = {k: 1.0 for k in keys}  # the house used more than expected
    pv = {k: (0.6 if 10 <= h < 15 else 0.0) for h, k in enumerate(keys)}  # the sun gave less on a cloudy day
    rep = L.review(day, house, pv, Battery(capacity_kwh=10), prices, 30)
    assert rep["house_error"] == 0.2 and L.margin > 0
    assert rep["sun_cloudy"] == 0.6 and L.state["solar_bias"]["cloudy"] < 1.0
    assert rep["saving"] > 0 and rep["best_factor"] in (0.6, 0.75, 0.9, 1.0, 1.1, 1.25)
    assert L.review(day, house, pv, Battery(), prices, 30) is None  # once a day

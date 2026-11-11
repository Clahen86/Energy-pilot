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
    # Quiet in the day: nothing from the grid, but the sun's surplus still fills it
    sun = [0] * 8 + [3.0] * 6 + [0] * 10
    p = plan_battery(day(prices, sun=sun), soc_now=10, b=Battery(quiet=frozenset(range(6, 22))))
    assert not any(s.action == "charge_grid" for s in p.steps[6:22])
    assert any(s.action == "charge_sun" for s in p.steps[8:14])
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



def test_quiet_hours_each_their_own(tmp_path):
    from types import SimpleNamespace

    from energy_pilot.engine import Engine

    ov = SimpleNamespace(settings={"quiet_battery_from": "22:00", "quiet_battery_to": "06:00", "quiet_car_from": "17:00",
                                   "quiet_car_to": "21:00"}, file=tmp_path / "s.json")
    e = Engine(SimpleNamespace(states={}, config={}), ov)
    assert e.quiet_hours("battery") == [22, 23, 0, 1, 2, 3, 4, 5]
    assert e.quiet_hours("car") == [17, 18, 19, 20]
    ov.settings = {"quiet_from": "23:00", "quiet_to": "01:00", "quiet_car": True}  # the old shared setting still works
    assert e.quiet_hours("car") == [23, 0] and e.quiet_hours("battery") == []


def test_quarter_hour_slots_use_the_cheap_quarters():
    from zoneinfo import ZoneInfo

    from energy_pilot.engine import Battery, Hour, plan_battery, resolution, split_slots

    tz = ZoneInfo("Europe/Copenhagen")
    t0 = datetime(2026, 11, 8, 0, tzinfo=tz)
    hours = [Hour(t0 + timedelta(hours=i), 2.0, 0.0, 1.0, 0.0) for i in range(4)]
    # Inside the second hour one quarter is very cheap, one very dear.
    fine = {t0 + timedelta(minutes=15 * q): 2.0 for q in range(16)}
    fine[t0 + timedelta(minutes=60)] = 0.2
    fine[t0 + timedelta(minutes=105)] = 5.0
    assert resolution(fine, t0) == 15
    slots = split_slots(hours, fine, t0)
    assert len(slots) == 16 and slots[0].length == 0.25 and abs(sum(s.house for s in slots) - 4.0) < 1e-9
    p = plan_battery(slots, 50, Battery(capacity_kwh=10, max_charge_kw=4, max_discharge_kw=4, efficiency=1.0))
    by = {s.start: s for s in p.steps}
    assert by[t0 + timedelta(minutes=60)].action == "charge_grid"  # buys in the cheap quarter
    assert by[t0 + timedelta(minutes=105)].action == "discharge"  # uses it in the dear one
    # A quarter moves the battery at most a quarter of an hour's power.
    assert all(abs(s.soc_end - s.soc_start) <= 4 * 0.25 / 10 * 100 + 2.01 for s in p.steps)


def test_hourly_prices_stay_hourly():
    from zoneinfo import ZoneInfo

    from energy_pilot.engine import Hour, split_slots

    tz = ZoneInfo("Europe/Copenhagen")
    t0 = datetime(2026, 11, 8, 0, tzinfo=tz)
    hours = [Hour(t0 + timedelta(hours=i), 2.0, 0.0, 1.0, 0.0) for i in range(3)]
    slots = split_slots(hours, {t0 + timedelta(hours=i): 2.0 for i in range(3)}, t0)
    assert len(slots) == 3 and slots[0].length == 1.0


def test_late_in_a_quarter_the_battery_still_covers_the_house():
    """At 07:26 the 07:15 quarter is nearly gone; the plan held the battery for the rest of it (grid bought)."""
    from zoneinfo import ZoneInfo

    from energy_pilot.engine import Battery, Hour, plan_battery, split_slots

    tz = ZoneInfo("Europe/Copenhagen")
    t0 = datetime(2026, 11, 10, 7, tzinfo=tz)
    prices = [4.9, 5.6, 5.4, 4.9, 4.7, 4.6, 4.8, 4.8, 5.4, 5.6, 6.2, 5.9, 5.3, 5.0, 3.3, 3.0]
    hours = [Hour(t0 + timedelta(hours=i), p, 0.0, 0.9, 0.0) for i, p in enumerate(prices)]
    fine = {t0 + timedelta(minutes=15 * q): prices[q // 4] for q in range(len(prices) * 4)}
    fine[t0 + timedelta(minutes=15)] = 5.6  # the quarter now is one the plan discharges in
    now = t0 + timedelta(minutes=26)
    slots = split_slots(hours, fine, now)
    b = Battery(capacity_kwh=11.5, min_soc=10, max_soc=100, max_charge_kw=3, max_discharge_kw=3, efficiency=0.9,
                grid_charge=True, wear=0.13)
    full = plan_battery(split_slots(hours, fine, t0 + timedelta(minutes=15)), 95, b)
    assert full.steps[0].action == "discharge"  # planned at the start of the quarter
    plan = plan_battery(slots, 95, b)
    assert plan.steps[0].action == "discharge"  # and still, 11 minutes in

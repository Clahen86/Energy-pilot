"""Fixes from the audit of 0.119.1: the car's mixed sun slots, stop-selling with a fixed sell price, appliances
sharing the sun and the fuse, and the power tariff counted once for the month's peak."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from energy_pilot.engine import Hour, plan_car

TZ = ZoneInfo("Europe/Copenhagen")


def test_a_mixed_sun_slot_costs_its_bought_share_too():
    # 70 % sun (sold at 1.0) and 30 % bought at 2.4: 1.42 a kWh - the night slot at 1.1 is cheaper.
    t0 = datetime(2026, 6, 1, tzinfo=TZ)
    sunny = Hour(t0 + timedelta(hours=12), 2.4, 1.0, 0.5, 1.9)
    night = Hour(t0 + timedelta(hours=2), 1.1, 0.0, 0.5, 0.0)
    assert plan_car([night, sunny], 2.0, 2.0, None, t0) == [night.start]
    # All sun: what it would have sold for (1.0) beats a grid slot at 1.2.
    full = Hour(t0 + timedelta(hours=12), 2.4, 1.0, 0.5, 2.5)
    dear = Hour(t0 + timedelta(hours=2), 1.2, 0.0, 0.5, 0.0)
    assert plan_car([dear, full], 2.0, 2.0, None, t0) == [full.start]


def _curtail(buy, settings):
    from datetime import timezone
    from types import SimpleNamespace

    from energy_pilot.curtail import Curtail

    st = {"curtail": {"on": True, "entity": "number.x_export_limit", "value": 0}, **settings}
    fee = float(st.get("sell_fee") or 0)
    eng = SimpleNamespace(tz=timezone.utc, sell_prices=lambda: {},
                          sell_fixed=lambda: float(st.get("sell_price") or 0) - fee if st.get("sell") else 0.0)
    ov = SimpleNamespace(settings=st, engine=eng, plan=lambda: {"hours": [
        {"t": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(), "price": buy}]})
    return Curtail(SimpleNamespace(states={}), ov, None)


def test_stop_selling_follows_the_fixed_sell_price():
    assert _curtail(-0.1, {"sell": True, "sell_price": 0.6}).sell_now() == 0.6  # paid 0.6: go on selling
    assert _curtail(0.5, {"sell": True, "sell_price": -0.2}).sell_now() == -0.2  # selling costs: stop
    assert _curtail(0.5, {"sell": True, "sell_price": 0.0, "sell_fee": 0.05}).sell_now() == -0.05
    assert _curtail(-0.1, {}).sell_now() == -0.1  # no sell price set: the buying price below 0, as before


def test_two_things_never_count_on_the_same_sun_or_fuse_room():
    from energy_pilot.things import Things

    t0 = datetime(2026, 6, 1)
    th = Things({})
    st = {"things": [{"id": "a", "kind": "battery", "switch": "s.a", "kwh": 1.0, "kw": 1.0, "mode": "sun"},
                     {"id": "b", "kind": "battery", "switch": "s.b", "kwh": 1.0, "kw": 1.0, "mode": "sun"}]}
    hs = [Hour(t0 + timedelta(hours=i), 1.0, 0.05, 0.5, 0) for i in range(24)]
    left = {hs[12].start: 1.0}  # 1 kWh of sun to spare: enough for one of them
    a, b = th.plan(st, hs, t0, left, {}, None)
    assert a["hours"] == [hs[12].start.isoformat()] and b["hours"] == []
    assert left == {hs[12].start: 1.0}  # the caller's own numbers aren't changed
    st["things"] = [dict(t, mode="cheap") for t in st["things"]]
    a, b = th.plan(st, hs, t0, {}, {h.start: 0.0 for h in hs}, 1.6)  # the house 0.5 + one 1 kW fits, not two
    assert a["hours"] and b["hours"] and not set(a["hours"]) & set(b["hours"])


def _peak_battery(**kw):
    from energy_pilot.engine import Battery

    return Battery(**{"capacity_kwh": 1, "max_charge_kw": 0.001, "max_discharge_kw": 0.001, "min_soc": 0, "max_soc": 100,
                      "grid_charge": False, "peak_kw": 1.0, "peak_price": 10.0, **kw})


def test_the_power_tariff_is_paid_once_for_the_peak():
    # 3 hours at 2 kW, price 1, the month's peak 1 kW at 10 a kW: 6 for the energy + 10 for one new peak = 16 (not 36),
    # the same in quarter hours (not 4 x as much).
    from energy_pilot.engine import plan_battery

    t0 = datetime(2026, 11, 9, 17, tzinfo=TZ)
    hourly = [Hour(t0 + timedelta(hours=i), 1.0, 0.0, 2.0, 0.0) for i in range(3)]
    quarters = [Hour(t0 + timedelta(minutes=15 * i), 1.0, 0.0, 0.5, 0.0, 0.25) for i in range(12)]
    for hs in (hourly, quarters):
        p = plan_battery(hs, 0, _peak_battery(), end_value=0)
        assert p.cost_without == 16.0 and p.cost == 16.0


def test_shaving_one_slot_of_many_isn_t_worth_it_but_the_only_peak_is():
    from energy_pilot.engine import plan_battery

    t0 = datetime(2026, 11, 9, 17, tzinfo=TZ)
    b = _peak_battery(capacity_kwh=10, max_charge_kw=5, max_discharge_kw=1, min_soc=0, efficiency=1.0)
    # One hour at 2 kW, the rest at 0.5: covering that hour from the battery saves the new peak (10).
    one = [Hour(t0 + timedelta(hours=i), 1.0, 0.0, 2.0 if i == 1 else 0.5, 0.0) for i in range(4)]
    p = plan_battery(one, 20, b, end_value=1.0)
    assert p.steps[1].action == "discharge" and p.cost < p.cost_without - 9


def test_held_back_sun_is_not_learned_from(tmp_path):
    from energy_pilot.learning import Learning

    lr = Learning.__new__(Learning)
    lr.state = {}
    t = datetime(2026, 6, 1, 13, 20, tzinfo=TZ)
    lr.mark_limited(t)
    pv = {"2026-06-01T12": 3.0, "2026-06-01T13": 1.0, "2026-06-01T14": 3.1}
    assert lr.unlimited(pv) == {"2026-06-01T12": 3.0, "2026-06-01T14": 3.1}
    dpv = {datetime(2026, 6, 1, h, tzinfo=TZ): 1.0 for h in (12, 13)}
    assert list(lr.unlimited(dpv)) == [datetime(2026, 6, 1, 12, tzinfo=TZ)]
    lr.mark_limited(t + timedelta(days=80))  # old hours are let go
    assert list(lr.state["limited"]) == ["2026-08-20T13"]


def test_the_user_is_told_when_the_inverter_keeps_refusing():
    from types import SimpleNamespace

    from energy_pilot import control as C

    c = C.Controller.__new__(C.Controller)
    c.ov = SimpleNamespace(settings={"control": {"battery": "control"}})
    c.ha = SimpleNamespace(states={})
    c.drift, c.is_battery, c._dst_note = {}, (lambda p: p == "battery"), (lambda: None)
    c.fails = {"battery": 2}
    assert not [w for w in c.watch_checks() if w["key"] == "not_taken"]
    c.fails["battery"] = 3
    assert [w for w in c.watch_checks() if w["key"] == "not_taken"]

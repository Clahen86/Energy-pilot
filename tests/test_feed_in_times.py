"""Feed-in by time in the own tariff plan (15c from 6-9pm), and a daily cap on paid feed-in."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from energy_pilot.engine import Battery, Hour, over_cap, plan_battery

TZ = ZoneInfo("Australia/Sydney")


def day_hours(sell_evening=0.15):
    t0 = datetime(2026, 11, 11, 0, tzinfo=TZ)
    out = []
    for i in range(24):
        price = 0.0 if 11 <= i < 14 else 0.40
        sell = sell_evening if 18 <= i < 21 else 0.0
        out.append(Hour(t0 + timedelta(hours=i), price, sell, 0.5, 0.0))
    return out


def test_free_power_and_evening_feed_in():
    hours = day_hours()
    b = Battery(capacity_kwh=40, max_charge_kw=10, max_discharge_kw=10, min_soc=10, export=True)
    p = plan_battery(hours, 10, b, end_value=0.0)
    acts = {s.start.hour: s.action for s in p.steps}
    assert any(acts[h] == "charge_grid" for h in (11, 12, 13))  # fills up on the free power
    assert any(acts[h] == "export" for h in (18, 19, 20))  # sells in the paid evening


def test_daily_cap_keeps_only_the_best_paid():
    hours = day_hours()
    b = Battery(capacity_kwh=40, max_charge_kw=10, max_discharge_kw=10, min_soc=10, export=True)
    p = plan_battery(hours, 10, b, end_value=0.0)
    sold = sum(-s.grid_kwh for s, h in zip(p.steps, hours) if h.sell > 0 and s.grid_kwh < 0)
    assert sold > 15
    for _ in range(3):
        over = over_cap(hours, p, 15)
        if not over:
            break
        for h in over:
            h.sell = 0.0
        p = plan_battery(hours, 10, b, end_value=0.0)
    paid = sum(-s.grid_kwh for s, h in zip(p.steps, hours) if h.sell > 0 and s.grid_kwh < 0)
    assert paid <= 15 + 10  # at most the cap plus the one slot that crosses it
    assert over_cap(hours, p, 15) == []


def test_tou_feed_in_prices():
    from energy_pilot.engine import Engine

    eng = Engine.__new__(Engine)
    eng.ha = type("H", (), {"config": {"country": "AU", "time_zone": "Australia/Sydney"}, "states": {}})()
    eng.ov = type("O", (), {"settings": {"price_source": "tou", "tou": {"default": 0.3, "periods": [],
                            "sell_default": 0.0, "sell_periods": [{"from": "18:00", "to": "21:00", "price": 0.15, "days": "all"}]}},
                            "role": lambda self, r: None})()
    sp = eng.sell_prices()
    vals = {t.hour: v for t, v in sp.items() if t.minute == 0}
    assert vals[19] == 0.15 and vals[12] == 0.0

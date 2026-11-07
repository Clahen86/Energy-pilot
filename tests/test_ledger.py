"""What the battery's power cost, and what it saved."""

from datetime import datetime, timedelta, timezone

from energy_pilot.ledger import Ledger

T = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)


def run(led, flows, price, sell=0.5, solar="free", step=timedelta(minutes=1)):
    t = T if led._at is None else led._at
    if led._at is None:
        led.tick(t, flows[0], price, sell, 10, 10, 1.0, solar)
    for f in flows:
        t += step
        led.tick(t, f, price, sell, 10, 10, 1.0, solar)


def test_grid_then_sun_lowers_the_average(tmp_path):
    led = Ledger(tmp_path)
    # 1 hour from the grid at 2.00: 3 kWh
    run(led, [{"battery": 3000, "pv": 0, "house": 0, "soc": 50}] * 60, 2.0)
    assert round(led.state["stored_cost"] / led.state["stored_kwh"], 2) == 2.0
    # 1 hour from the sun: 3 kWh more, free -> average 1.00
    run(led, [{"battery": 3000, "pv": 4000, "house": 1000, "soc": 80}] * 60, 2.0)
    assert round(led.summary(T)["avg_cost"], 2) == 1.0
    # discharging keeps the average
    run(led, [{"battery": -2000, "pv": 0, "house": 2000, "soc": 60}] * 60, 3.0)
    assert round(led.summary(T)["avg_cost"], 2) == 1.0 and round(led.state["stored_kwh"], 1) == 4.0


def test_sun_valued_at_sell_price(tmp_path):
    led = Ledger(tmp_path)
    run(led, [{"battery": 2000, "pv": 3000, "house": 1000, "soc": 50}] * 60, 2.0, sell=0.6, solar="sell")
    assert round(led.summary(T)["avg_cost"], 2) == 0.6


def test_saved_is_measured(tmp_path):
    led = Ledger(tmp_path)
    # the battery covers 2 kW of house at 3.00 for an hour: saved 6.00
    run(led, [{"battery": -2000, "pv": 0, "house": 2000, "soc": 60, "grid": 0}] * 60, 3.0)
    assert led.summary(T)["today"] == 6.0
    # charging 2 kW from the grid at 1.00 for an hour: costs 2.00
    run(led, [{"battery": 2000, "pv": 0, "house": 0, "soc": 70, "grid": 2000}] * 60, 1.0)
    assert led.summary(T)["today"] == 4.0


def test_empty_battery_starts_over_and_other_system_wins(tmp_path):
    led = Ledger(tmp_path)
    run(led, [{"battery": 3000, "pv": 0, "house": 0, "soc": 50}] * 30, 2.0)
    run(led, [{"battery": -100, "pv": 0, "house": 100, "soc": 10}] * 2, 2.0)
    assert led.state["stored_kwh"] == 0
    assert led.summary(T, other_avg=1.99)["avg_cost"] == 1.99

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
    run(led, [{"battery": -100, "pv": 0, "house": 100, "soc": 10}] * 7, 2.0)  # empty for a few minutes
    assert led.state["stored_kwh"] == 0
    assert led.summary(T, other_avg=1.99)["avg_cost"] == 1.99


def test_one_wrong_low_reading_keeps_the_cost():
    from datetime import datetime, timedelta
    from energy_pilot.ledger import Ledger
    import tempfile, pathlib
    led = Ledger(pathlib.Path(tempfile.mkdtemp()))
    t = datetime(2026, 11, 8, 12)
    led.state.update(stored_kwh=9.0, stored_cost=23.0)
    flow = {"house": 500, "pv": 0, "battery": 0, "soc": 80, "grid": 500, "ev": 0}
    led.tick(t, flow, 2.5, 0.0, 11.7, 10, 0.92)
    led.tick(t + timedelta(minutes=1), {**flow, "soc": 0}, 2.5, 0.0, 11.7, 10, 0.92)   # a glitch
    led.tick(t + timedelta(minutes=2), flow, 2.5, 0.0, 11.7, 10, 0.92)
    assert round(led.state["stored_cost"], 1) == 23.0


def test_sun_and_battery_saving(tmp_path):
    led = Ledger(tmp_path)
    # 1 hour: house 3 kW at 2.00, sun gives 1 kW, the battery 2 kW, nothing bought
    run(led, [{"battery": -2000, "pv": 1000, "house": 3000, "grid": 0, "soc": 60}] * 60, 2.0)
    s = led.summary(T)
    assert round(s["today"], 1) == 4.0  # the battery alone: 2 kWh at 2.00
    assert round(s["all"]["today"], 1) == 6.0  # sun and battery: all 3 kWh the house used
    assert s["all"]["since"] == T.date().isoformat()


def test_sun_selling_counts_with_sun(tmp_path):
    led = Ledger(tmp_path)
    # 1 hour: sun 4 kW, house 1 kW, 3 kW sold at 0.50 - the battery idle
    run(led, [{"battery": 0, "pv": 4000, "house": 1000, "grid": -3000, "soc": 60}] * 60, 2.0, sell=0.5)
    s = led.summary(T)
    assert round(s["today"], 2) == 0.0
    assert round(s["all"]["today"], 2) == 3.5  # 1 kWh not bought (2.00) + 3 kWh sold (1.50)

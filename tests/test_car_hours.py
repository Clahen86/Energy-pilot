"""The car's own hours in the plan: tap an hour and choose "charge the car here" or "not the car here"."""

from datetime import datetime, timedelta, timezone

from energy_pilot.engine import Hour, car_pins, plan_car

T0 = datetime(2026, 11, 28, 0, tzinfo=timezone.utc)
PRICES = [2.3, 2.2, 2.1, 2.0, 1.9, 1.8, 3.0, 4.0]  # cheapest at 05, then 04


def _hours():
    return [Hour(T0 + timedelta(hours=i), p, 0.0, 0.8, 0.0) for i, p in enumerate(PRICES)]


def _key(h):
    return (T0 + timedelta(hours=h)).strftime("%Y-%m-%dT%H")


def test_without_choices_the_cheapest():
    assert plan_car(_hours(), 7.4, 3.7, T0 + timedelta(hours=8), T0) == [T0 + timedelta(hours=4), T0 + timedelta(hours=5)]


def test_a_chosen_hour_is_always_used_and_the_rest_filled():
    got = plan_car(_hours(), 7.4, 3.7, T0 + timedelta(hours=8), T0, pins={_key(0): "charge"})
    assert got == [T0, T0 + timedelta(hours=5)]  # 00 as chosen, then only the cheapest one more


def test_a_skipped_hour_is_never_used():
    got = plan_car(_hours(), 7.4, 3.7, T0 + timedelta(hours=8), T0, pins={_key(5): "skip"})
    assert got == [T0 + timedelta(hours=3), T0 + timedelta(hours=4)]


def test_chosen_even_after_ready_or_in_quiet_hours():
    got = plan_car(_hours(), 3.7, 3.7, T0 + timedelta(hours=3), T0, skip={T0 + timedelta(hours=7)}, pins={_key(7): "charge"})
    assert got == [T0 + timedelta(hours=7)]


def test_quarter_slots_follow_their_hour():
    slots = [Hour(T0 + timedelta(minutes=15 * i), 2.0 + i / 100, 0.0, 0.2, 0.0, 0.25) for i in range(16)]
    got = plan_car(slots, 3.7, 3.7, T0 + timedelta(hours=4), T0, pins={_key(3): "charge"})
    assert got == [T0 + timedelta(hours=3, minutes=15 * q) for q in range(4)]


def test_pins_per_charger_from_the_settings():
    st = {"car_manual": {"car": {"2026-11-28T03": "charge", "x": "odd"}, "car2": {"2026-11-28T04": "skip"}}}
    assert car_pins(st, "car") == {"2026-11-28T03": "charge"} and car_pins(st, "car2") == {"2026-11-28T04": "skip"}
    assert car_pins({}, "car") == {} and car_pins({"car_manual": {"car": "bad"}}, "car") == {}

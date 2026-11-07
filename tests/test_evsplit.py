"""Is the car in the house's use?"""

from datetime import datetime, timedelta

from energy_pilot.evsplit import detect, subtract

T0 = datetime(2026, 10, 1)


def rows(days, car_in_house):
    house, ev = [], []
    for d in range(days):
        for h in range(24):
            t = T0 + timedelta(days=d, hours=h)
            base = 0.6 + (0.8 if 17 <= h < 20 else 0)
            car = 7.0 if (d % 3 == 0 and h in (1, 2, 3)) else 0.0
            house.append((t, base + (car if car_in_house else 0)))
            ev.append((t, car))
    return house, ev


def test_car_in_the_house_sensor_is_found_and_taken_out():
    house, ev = rows(20, True)
    assert detect(house, ev) is True
    clean = subtract(house, ev)
    assert max(kw for _, kw in clean) < 1.5


def test_house_without_the_car():
    assert detect(*rows(20, False)) is False


def test_not_enough_charging_seen():
    house, ev = rows(20, True)
    assert detect(house, [(t, 0.0) for t, _ in ev]) is None

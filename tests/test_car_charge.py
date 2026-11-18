"""The car card's charge: how much of it the sun gave, and what it cost."""

from datetime import datetime, timedelta

from energy_pilot.ghost import Ghosts


def test_sun_part_comes_after_the_grid_and_the_battery():
    assert Ghosts.sun_to_car(4000, 2000, 1500, -800) == 1700  # grid 1500, battery 800, the sun the rest
    assert Ghosts.sun_to_car(4000, 0, 4000, 0) == 0  # night
    assert Ghosts.sun_to_car(3000, 5000, -1000, 0) == 3000  # selling too: all from the sun
    assert Ghosts.sun_to_car(0, 5000, -5000, 0) == 0


def test_charge_counts_sun_and_cost():
    g, t = Ghosts({}), datetime(2026, 11, 18, 12)
    g.see("car", t, True, 0, 2.0, 30)
    for i in range(120):  # an hour at 4 kW, 1 kW of it from the sun
        g.see("car", t + timedelta(seconds=30 * (i + 1)), True, 4000, 2.0, 30, sun_w=1000, sell=0.5)
    own = g.part("car")["own"]
    assert round(own["kwh"], 2) == 4.0 and round(own["sun_kwh"], 2) == 1.0
    assert round(own["cost"], 2) == 6.5  # 3 kWh at 2.0 + 1 kWh at what selling pays

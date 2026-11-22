"""An unsure sun forecast: the battery plan counts on a little less sun - a sure one changes nothing."""

from energy_pilot.engine import doubt_sun


def test_unsure_forecast_counts_on_a_little_less():
    assert doubt_sun(4.0, 4.0, 1.0) == 4.0 * (1 - 0.15 * 0.75)  # poor day far below: 11 % less
    assert doubt_sun(4.0, 4.0, 3.9) > 3.98  # a clear sky: nearly the same


def test_no_poor_day_or_no_sun_changes_nothing():
    assert doubt_sun(4.0, 4.0, None) == 4.0  # not Solcast
    assert doubt_sun(0.0, 0.0, 0.0) == 0.0
    assert doubt_sun(3.0, 4.0, 4.0) == 3.0


def test_the_learned_figure_is_scaled_not_replaced():
    assert round(doubt_sun(2.0, 4.0, 2.0), 3) == round(2.0 * (1 - 0.15 * 0.5), 3)

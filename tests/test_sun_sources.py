"""The plan knows the sun hour by hour from Solcast, Home Assistant's Energy dashboard forecast (Forecast.Solar …),
Open-Meteo's wh_period - or its own learned forecast."""

from datetime import datetime, timedelta, timezone

from energy_pilot.engine import solar_hours


def test_energy_dashboard_forecast_adds_arrays():
    fc = {"a": {"wh_hours": {"2026-11-11T10:00:00+00:00": 1200, "2026-11-11T11:00:00+00:00": 800}},
          "b": {"wh_hours": {"2026-11-11T10:00:00+00:00": 300}}, "other": {"wh_hours": {"2026-11-11T10:00:00+00:00": 9999}}}
    out = solar_hours(fc, ["a", "b"])
    t = datetime(2026, 11, 11, 10, tzinfo=timezone.utc)
    assert out[t] == 1.5 and out[t + timedelta(hours=1)] == 0.8
    assert solar_hours(None, ["a"]) == {}


def test_house_worked_out_from_the_other_meters():
    """No house sensor: grid + sun - battery - car per hour, with the meters' own signs; never below 0."""
    from energy_pilot.engine import computed_house

    t = [datetime(2026, 11, 10, h, tzinfo=timezone.utc) for h in range(3)]
    grid = {t[0]: 1.0, t[1]: -2.0, t[2]: 0.5}
    pv = {t[0]: 0.0, t[1]: 3.0, t[2]: 0.0}
    batt = {t[0]: 0.0, t[1]: 0.5, t[2]: -0.3}  # charging +
    ev = {t[2]: 0.2}
    assert computed_house(grid, pv, batt, ev) == [(t[0], 1.0), (t[1], 0.5), (t[2], 0.6)]
    assert computed_house({t[0]: -1.0}, {t[0]: 0.0}, {}, {}, grid_sign=-1) == [(t[0], 1.0)]
    assert computed_house({t[0]: -3.0}, {t[0]: 0.0}, {}, {}) == [(t[0], 0.0)]

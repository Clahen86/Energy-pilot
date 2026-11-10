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

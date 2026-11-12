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


def test_hours_without_battery_history_are_left_out():
    """A battery sensor made lately: the night's charging before it existed must not become house use."""
    from energy_pilot.engine import computed_house

    t = [datetime(2026, 11, 10, h, tzinfo=timezone.utc) for h in range(3)]
    grid = {t[0]: 6.0, t[1]: 6.0, t[2]: 6.0}  # 1 kW house + 5 kW into the battery
    pv = {x: 0.0 for x in t}
    batt = {t[2]: 5.0}  # the sensor only has the last hour
    assert computed_house(grid, pv, batt, {}) == [(t[2], 1.0)]


def test_every_charger_is_taken_out():
    """Charger 1 and the extra chargers are added up when the cars are taken out of the house's history."""
    import asyncio

    from energy_pilot.engine import Engine

    t = datetime(2026, 11, 10, 18, tzinfo=timezone.utc)
    eng = Engine.__new__(Engine)
    eng.ov = type("O", (), {"settings": {"chargers": [{"power": "sensor.keba2_power", "plug": "binary_sensor.keba2_plug"}]},
                            "role": lambda self, r: "sensor.keba1_power" if r == "ev_power" else None})()

    async def hourly(e, days):
        return [(t, {"sensor.keba1_power": 7.0, "sensor.keba2_power": 3.5}[e])]
    eng._hourly_kw = hourly
    assert asyncio.run(eng._all_cars(1)) == {t: 10.5}

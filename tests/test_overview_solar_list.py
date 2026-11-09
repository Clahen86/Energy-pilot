"""The second solar forecast can be picked even when it isn't named like Solcast's."""

from types import SimpleNamespace

from energy_pilot.overview import Overview


def test_forecast_solar_is_listed_first():
    st = lambda u: {"state": "5", "attributes": {"unit_of_measurement": u}}  # noqa: E731
    ha = SimpleNamespace(states={"sensor.solcast_pv_forecast_forecast_today": st("kWh"),
                                 "sensor.energy_production_today": st("kWh"),
                                 "sensor.grid_import_total": st("kWh"),
                                 "sensor.pv_power": st("W")})
    ov = Overview.__new__(Overview)
    ov.ha, ov.settings, ov.engine, ov.detected = ha, {}, None, {}
    rows = ov.candidates()["solar_today"]
    ids = [r["entity_id"] for r in rows]
    assert set(ids[:2]) == {"sensor.solcast_pv_forecast_forecast_today", "sensor.energy_production_today"}
    assert "sensor.grid_import_total" in ids and "sensor.pv_power" not in ids

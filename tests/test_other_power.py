"""Other power made on the spot (a small wind turbine): in the flow and the balance, not taken for the sun."""
import json

from energy_pilot.overview import Overview


def _ov(tmp_path, roles):
    w = lambda v: {"state": str(v), "attributes": {"unit_of_measurement": "W", "device_class": "power"}}  # noqa: E731

    class HA:
        states = {"sensor.pv": w(400), "sensor.wind": w(1200), "sensor.grid": w(100), "sensor.batt": w(0)}
        config = {"time_zone": "UTC"}

    (tmp_path / "energy_pilot_settings.json").write_text(json.dumps({"roles": roles}))
    return Overview(HA(), tmp_path)


def test_wind_counts_in_the_balance_but_not_as_sun(tmp_path):
    f = _ov(tmp_path, {"pv_power": "sensor.pv", "other_power": "sensor.wind", "grid_power": "sensor.grid",
                       "battery_power": "sensor.batt"}).flow()
    assert f["sun"] == 400 and f["other"] == 1200 and f["pv"] == 1600
    assert f["house"] == 1700  # sun + wind + grid - battery


def test_never_found_by_itself(tmp_path):
    f = _ov(tmp_path, {"pv_power": "sensor.pv", "grid_power": "sensor.grid", "battery_power": "sensor.batt"}).flow()
    assert f["other"] is None and f["pv"] == 400 and f["sun"] == 400 and f["house"] == 500

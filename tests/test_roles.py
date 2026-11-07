"""Several solar arrays are added up, and lists show sensors without a device class."""

import json

from energy_pilot.overview import Overview


class HA:
    def __init__(self, states):
        self.states = states
        self.config = {"time_zone": "UTC"}


def st(state, **attrs):
    return {"state": state, "attributes": attrs}


def make(tmp_path, roles):
    states = {
        "sensor.east_array_power": st("1200", device_class="power", unit_of_measurement="W", friendly_name="East"),
        "sensor.west_array": st("0.8", unit_of_measurement="kW", friendly_name="West (template)"),  # no device_class
        "sensor.victron_battery": st("63", unit_of_measurement="%", friendly_name="Victron battery"),
        "sensor.humidity": st("55", device_class="humidity", unit_of_measurement="%"),
    }
    (tmp_path / "energy_pilot_settings.json").write_text(json.dumps({"roles": roles}))
    o = Overview(HA(states), tmp_path)
    return o


def test_two_arrays_add_up(tmp_path):
    o = make(tmp_path, {"pv_power": ["sensor.east_array_power", "sensor.west_array"]})
    assert o.role_all("pv_power") == ["sensor.east_array_power", "sensor.west_array"]
    assert o.role("pv_power") == "sensor.east_array_power"
    assert o.flow()["pv"] == 2000


def test_lists_show_sensors_without_device_class(tmp_path):
    c = make(tmp_path, {}).candidates()
    assert "sensor.west_array" in [r["entity_id"] for r in c["pv_power"]]
    soc = [r["entity_id"] for r in c["battery_soc"]]
    assert "sensor.victron_battery" in soc and "sensor.humidity" not in soc


def test_battery_sign_reversed_by_choice(tmp_path):
    o = make(tmp_path, {"battery_power": "sensor.east_array_power"})
    o.settings["battery_sign"] = -1
    assert o.flow()["battery"] == -1200


def test_battery_sign_found_from_the_level():
    from energy_pilot.engine import Engine

    class Ov:
        file = None

    e = Engine.__new__(Engine)
    e.learning = type("L", (), {"state": {}})()
    e._sign_prev = None
    soc = 50.0
    for _ in range(5):  # Fox ESS: +2000 W while the level falls
        for _ in range(10):
            e.watch_sign(2000, soc)
            soc -= 0.25
        e.watch_sign(0, soc)
    assert e.sign_found() == -1


def test_amber_feed_in_forecast_is_read():
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from energy_pilot.pricefeed import parse

    tz = ZoneInfo("Australia/Sydney")
    t0 = datetime(2026, 11, 8, 10, tzinfo=tz)
    attrs = {"forecasts": [{"start_time": (t0 + timedelta(minutes=30 * i)).isoformat(), "per_kwh": 0.05 + i * 0.01} for i in range(4)]}
    p = parse(attrs, tz, t0.replace(hour=0))
    assert p[t0 + timedelta(minutes=60)] == 0.07


def test_a_chosen_sensor_outside_the_filters_does_not_break_the_list(tmp_path):
    """Crash report: a found sensor that the filters leave out was added without its 'guess' flag."""
    o = make(tmp_path, {"battery_power": "sensor.humidity"})  # chosen, but not a power sensor
    c = o.candidates()
    assert c["battery_power"][0]["entity_id"] == "sensor.humidity"

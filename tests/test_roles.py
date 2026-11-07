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

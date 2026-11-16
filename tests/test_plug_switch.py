from energy_pilot import chargers


def test_extra_charger_switch_without_plug_sensor_counts_as_plugged():
    states = {"sensor.p": {"state": "0", "attributes": {"unit_of_measurement": "W"}}}
    assert chargers.read(states, {"power": "sensor.p", "switch": "switch.plug"})["plug"] is True
    assert chargers.read(states, {"power": "sensor.p"})["plug"] is False


def test_main_charger_switch_without_plug_sensor_counts_as_plugged(tmp_path):
    import json
    from energy_pilot.overview import Overview

    class HA:
        states = {"switch.car_plug": {"state": "off", "attributes": {}}}
        config = {"time_zone": "UTC"}

    (tmp_path / "energy_pilot_settings.json").write_text(json.dumps({"roles": {}, "ev_switch": "switch.car_plug"}))
    assert Overview(HA(), tmp_path).flow()["plug"] is True
    (tmp_path / "energy_pilot_settings.json").write_text(json.dumps({"roles": {}}))
    assert not Overview(HA(), tmp_path).flow()["plug"]

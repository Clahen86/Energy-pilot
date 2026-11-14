"""The setup for the developer: names without the user's device name (unless shared), what each is used for, errors."""

from types import SimpleNamespace

from energy_pilot import setupinfo

REG = {"select.claus_inverter_export_limiter": {"device_id": "d1", "platform": "solarman"},
       "sensor.claus_inverter_battery_soc": {"device_id": "d1", "platform": "solarman"},
       "number.x_y": {"device_id": "d2", "platform": "huawei_solar", "translation_key": "grid_export_limit"},
       "number.lounge_thing": {"device_id": None, "platform": "template"}}
DEV = {"d1": {"name": "Claus inverter", "manufacturer": "Deye", "model": "SUN-10K"}, "d2": {"name": "Other"}}


def test_mask():
    assert setupinfo.mask("select.claus_inverter_export_limiter", REG, DEV) == "select.<device>_export_limiter"
    assert setupinfo.mask("number.x_y", REG, DEV) == "number.<device>_grid_export_limit"
    assert setupinfo.mask("number.lounge_thing", REG, DEV) == "number.<name>"


def _ov(full_names=False):
    states = {"select.claus_inverter_export_limiter": {"state": "Disabled", "attributes": {"options": ["Disabled", "Enabled"]}},
              "sensor.claus_inverter_battery_soc": {"state": "55", "attributes": {"unit_of_measurement": "%"}}}
    ctl = SimpleNamespace(
        _ent_reg=REG, _devices=DEV, entities={"battery": ["select.claus_inverter_export_limiter"], "car": []},
        platforms={"battery": "solarman", "car": None}, parts=lambda: ["battery", "car", "generator"],
        is_battery=lambda p: p == "battery", profile_key=lambda p: "solarman", mode=lambda p: "control", blocked=lambda p: None,
        intents=lambda: {"battery": {"intent": "normal", "ctx": {}}},
        calls=lambda p, w: [{"domain": "select", "service": "select_option", "data": {"entity_id": "select.claus_inverter_export_limiter"}}] if w["intent"] == "export" else [],
        last={"battery": {"result": "failed: select.select_option"}}, part_errors={"battery": ["export: refused"]}, drift={})
    roles = {"battery_soc": "sensor.claus_inverter_battery_soc"}
    return SimpleNamespace(controller=ctl, ha=SimpleNamespace(states=states), settings={"battery_kwh": 12, "curtail": {}},
                           role=lambda r: roles.get(r), source=lambda r: "integration:nordpool")


def test_collect_cleaned():
    out = setupinfo.collect(_ov(), False)
    bat = out["devices"][0]
    assert bat["kind"] == "battery" and bat["profile"] == "solarman" and bat["manufacturer"] == "Deye"
    names = {e["name"]: e["use"] for e in bat["entities"]}
    assert names == {"sensor.<device>_battery_soc": "battery_soc", "select.<device>_export_limiter": "export"}
    assert bat["ok"] is False and bat["errors"] == ["export: refused"]
    assert "claus" not in str(out).lower()
    assert out["sizes"]["battery"] == "10-15 kWh" and out["devices"][1]["platform"] == "nordpool"


def test_collect_full_names():
    out = setupinfo.collect(_ov(), True)
    assert "select.claus_inverter_export_limiter" in str(out)

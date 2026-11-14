"""The setup for the developer: names without the user's device name (unless shared), what each is used for, errors."""

from types import SimpleNamespace

from energy_pilot import setupinfo

REG = {"select.claus_inverter_export_limiter": {"device_id": "d1", "platform": "solarman"},
       "sensor.claus_inverter_battery_soc": {"device_id": "d1", "platform": "solarman"},
       "number.x_y": {"device_id": "d2", "platform": "huawei_solar", "translation_key": "grid_export_limit"},
       "number.lounge_thing": {"device_id": None, "platform": "template"}}
DEV = {"d1": {"name": "Claus inverter", "manufacturer": "Deye", "model": "SUN-10K"}, "d2": {"name": "Other"}}


def test_mask():
    words = [("claus", "<person>")]
    assert setupinfo.mask("select.claus_inverter_export_limiter", REG, DEV, words) == "select.<device>_export_limiter"
    assert setupinfo.mask("number.x_y", REG, DEV, words) == "number.x_y"  # nothing personal: the whole name
    assert setupinfo.mask("number.lounge_thing", REG, DEV, words) == "number.lounge_thing"  # rooms stay
    assert setupinfo.mask("sensor.claus_keba_power", REG, DEV, words) == "sensor.<person>_keba_power"


def test_personal_words():
    ov = SimpleNamespace(ha=SimpleNamespace(states={"person.lilly": {"attributes": {"friendly_name": "Lilly Hansen"}},
                                                    "zone.work": {"attributes": {"friendly_name": "Work"}}}, config={"location_name": "Motelvej"}))
    w = dict(setupinfo.personal_words(ov, {"d": {"name_by_user": "Keba garage"}}, ["Living room"]))
    assert dict(setupinfo.personal_words(SimpleNamespace(ha=SimpleNamespace(states={"person.s": {"attributes": {"friendly_name": "Søren"}}}, config={})), {}, []))["soren"] == "<person>"
    assert w["lilly"] == "<person>" and w["hansen"] == "<person>" and "living_room" not in w
    assert w["motelvej"] == "<home>" and w["keba_garage"] == "<device>" and w["work"] == "<zone>"


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
    ctl._areas = []
    return SimpleNamespace(controller=ctl, ha=SimpleNamespace(states={**states, "person.claus": {"attributes": {"friendly_name": "Claus"}}}, config={}), settings={"battery_kwh": 12, "curtail": {}},
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


def test_brand_from_another_entity_or_the_integration():
    reg = {"sensor.tpl_power": {"platform": "template"}, "sensor.keba_x": {"platform": "keba", "device_id": "k"}}
    devs = {"k": {"manufacturer": "KEBA", "model": "P30"}}
    assert setupinfo.brand_device(["sensor.tpl_power", "sensor.keba_x"], reg, devs)["model"] == "P30"
    assert setupinfo.brand_device(["sensor.tpl_power"], reg, devs, "keba")["manufacturer"] == "KEBA"
    assert setupinfo.brand_device(["sensor.tpl_power"], reg, devs, None, ["k"])["model"] == "P30"

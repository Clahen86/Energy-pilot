"""What the shared setups showed: a car's level taken for the house battery (TeslaMate through MQTT, a SEAT through a
data service), an aircon's power taken for the car charger."""
import asyncio
from types import SimpleNamespace

from energy_pilot import checks
from energy_pilot.detect import detect
from energy_pilot.engine import Battery


class HA:
    def __init__(self, entities, devices, states):
        self.entities, self.devices, self.states = entities, devices, states

    async def command(self, msg):
        return {"config/entity_registry/list": self.entities, "config/device_registry/list": self.devices,
                "energy/get_prefs": {}}[msg["type"]]


SOC = {"state": "60", "attributes": {"device_class": "battery", "unit_of_measurement": "%"}}


def test_a_car_through_mqtt_is_no_house_battery():
    ents = [{"entity_id": "sensor.overdrive_state_of_charge", "platform": "mqtt", "device_id": "car"}]
    devs = [{"id": "car", "manufacturer": "Tesla", "model": "Model 3", "name": "Overdrive"}]
    found = asyncio.run(detect(HA(ents, devs, {"sensor.overdrive_state_of_charge": SOC})))
    assert "battery_soc" not in found


def test_a_powerwall_and_a_battery_box_still_are():
    for maker, model in (("Tesla", "Powerwall 2"), ("BYD", "Battery-Box Premium HVS")):
        ents = [{"entity_id": "sensor.home_state_of_charge", "platform": "mqtt", "device_id": "b"}]
        devs = [{"id": "b", "manufacturer": maker, "model": model, "name": "Battery"}]
        found = asyncio.run(detect(HA(ents, devs, {"sensor.home_state_of_charge": SOC})))
        assert found["battery_soc"]["entity_id"] == "sensor.home_state_of_charge", maker


def _engine(roles, registry=()):
    ov = SimpleNamespace(settings={}, flow=lambda: {"soc": 50}, role=lambda r: roles.get(r),
                         ha=SimpleNamespace(states={}, config={}), controller=SimpleNamespace(registry=list(registry), mode=lambda p: "shadow"))
    return SimpleNamespace(ov=ov, ha=ov.ha, batt_learn=SimpleNamespace(capacity=lambda: None), ev_detected=None,
                           grid_peak=SimpleNamespace(kw=lambda: None))


def test_told_when_the_charger_power_is_an_aircon_or_the_level_a_car():
    keys = [c["key"] for c in checks.run(_engine({"ev_power": "sensor.aircon_power"}), [], Battery(), None, 0.0)]
    assert keys == ["ev_power_other"]
    eng = _engine({"battery_soc": "sensor.haval_soc"}, [{"entity_id": "sensor.haval_soc", "platform": "gwm_ora"}])
    assert [c["key"] for c in checks.run(eng, [], Battery(), None, 0.0)] == ["soc_not_house"]
    assert checks.run(_engine({"ev_power": "sensor.easee_power", "battery_soc": "sensor.inv_soc"}), [], Battery(), None, 0.0) == []


def test_fox_grid_consumption_is_not_the_house():
    """Fox ESS Modbus: "grid consumption power" came first in the registry and was taken for the house's use -
    the house model then learned the grid's night charging as the house."""
    kw = {"device_class": "power", "unit_of_measurement": "kW"}
    ids = ["sensor.foxess_grid_consumption_power", "sensor.foxess_feed_in_power", "sensor.foxess_load_power"]
    ents = [{"entity_id": e, "platform": "foxess_modbus", "device_id": "fox"} for e in ids]
    states = {e: {"state": "0.3", "attributes": kw} for e in ids}
    found = asyncio.run(detect(HA(ents, [{"id": "fox", "name": "FoxESS"}], states)))
    assert found["house_power"]["entity_id"] == "sensor.foxess_load_power"
    ents, states = ents[:2], {e: states[e] for e in ids[:2]}  # without a load sensor: none rather than the grid's
    found = asyncio.run(detect(HA(ents, [{"id": "fox", "name": "FoxESS"}], states)))
    assert "house_power" not in found


def test_another_house_meter_is_learned_from_at_once():
    from energy_pilot.engine import Engine

    roles = {"house_power": "sensor.foxess_grid_consumption_power"}
    eng = SimpleNamespace(ov=SimpleNamespace(role_all=lambda r: [roles[r]] if r in roles else []))
    before = Engine.learn_roles(eng)
    roles["house_power"] = "sensor.foxess_load_power"
    assert Engine.learn_roles(eng) != before


def test_a_garden_sensor_is_no_house_battery():
    """"Battery level" alone, with no home battery's power anywhere: a Czech garden sensor was taken for it."""
    pct = {"device_class": "battery", "unit_of_measurement": "%"}
    states = {"sensor.zahony_cibule_2026_battery_level": {"state": "80", "attributes": pct}}
    assert "battery_soc" not in asyncio.run(detect(HA([], [], states)))
    states["sensor.battery_power"] = {"state": "300", "attributes": {"device_class": "power", "unit_of_measurement": "W"}}
    states["sensor.battery_level"] = {"state": "55", "attributes": pct}  # Sungrow through Modbus YAML: kept
    assert asyncio.run(detect(HA([], [], states)))["battery_soc"]["entity_id"] == "sensor.battery_level"

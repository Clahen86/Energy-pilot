"""A cold battery charges slower: learned from its own temperature - an indoor one never changes."""

from types import SimpleNamespace

from energy_pilot.blend import BatteryLearner
from energy_pilot.engine import Engine


def test_learns_how_much_slower_it_charges_when_cold():
    bl = BatteryLearner({})
    for _ in range(20):
        bl.see_temp(5000, 50, 20.0)
        bl.see_temp(2500, 50, 2.0)
    assert bl.cold_share(2.0) == 0.5
    assert bl.cold_share(20.0) == 1.0 and bl.cold_share(None) == 1.0
    assert bl.cold_share(10.0) == 1.0  # cool: not seen yet


def test_indoor_or_unseen_battery_stays_at_full_power():
    bl = BatteryLearner({})
    for _ in range(40):
        bl.see_temp(5000, 50, 21.0)  # always warm
    assert bl.cold_share(21.0) == 1.0
    bl.see_temp(5000, 90, 2.0)  # near full: the taper's, not the cold's
    assert (bl.s.get("temp_w") or {}).get("cold") is None


def test_finds_the_battery_temperature_not_the_inverters():
    reg = [{"entity_id": "sensor.inv_soc", "device_id": "d"},
           {"entity_id": "sensor.inv_inverter_temperature", "device_id": "d"},
           {"entity_id": "sensor.inv_battery_temperature", "device_id": "d"},
           {"entity_id": "sensor.other_battery_temperature", "device_id": "x"}]
    t = {"attributes": {"device_class": "temperature"}}
    states = {"sensor.inv_inverter_temperature": {**t, "state": "45"}, "sensor.inv_battery_temperature": {**t, "state": "7.5"},
              "sensor.other_battery_temperature": {**t, "state": "30"}}
    eng = Engine.__new__(Engine)
    eng.ha = SimpleNamespace(states=states)
    eng.ov = SimpleNamespace(controller=SimpleNamespace(registry=reg, battery_device=None), role=lambda r: "sensor.inv_soc")
    assert eng.battery_temp() == 7.5

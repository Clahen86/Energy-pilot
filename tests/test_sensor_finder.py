"""The sensor finder: learned from setups (training/sensors.py), used by detect for what its rules didn't find."""
import asyncio
import importlib.util
from pathlib import Path

from energy_pilot.detect import detect

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("sensors_train", ROOT / "training" / "sensors.py")
sensors_train = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sensors_train)


def _setup(home, key, name, role="battery_soc", plat="newinv"):
    return {"home": home, "devices": [{"entities": [{"name": name, "use": role, "platform": plat, "key": key}]}]}


def test_learns_only_what_homes_agree_on():
    rows = [_setup("a", "soc_k", "sensor.<device>_bat_level"), _setup("b", "soc_k", "sensor.<device>_bat_level"),
            _setup("c", "other", "sensor.<device>_lonely")]
    m = sensors_train.build(rows)
    assert m["keys"] == {"newinv|soc_k": {"role": "battery_soc", "n": 2}}
    assert m["names"] == {"newinv|sensor|bat_level": {"role": "battery_soc", "n": 2}}


class HA:
    def __init__(self, entities, states):
        self.entities, self.states = entities, states

    async def command(self, msg):
        return {"config/entity_registry/list": self.entities, "config/device_registry/list": [], "energy/get_prefs": {}}[msg["type"]]


def test_detect_uses_the_finder_only_for_what_is_missing():
    ents = [{"entity_id": "sensor.myinv_bat_level", "platform": "newinv", "translation_key": None},
            {"entity_id": "sensor.myinv_x", "platform": "newinv", "translation_key": "pvk"}]
    states = {"sensor.myinv_bat_level": {"state": "55", "attributes": {"unit_of_measurement": "%"}},
              "sensor.myinv_x": {"state": "1200", "attributes": {"unit_of_measurement": "W"}}}
    shared = {"keys": {"newinv|pvk": {"role": "pv_power", "n": 3}}, "names": {"newinv|sensor|bat_level": {"role": "battery_soc", "n": 2}}}
    found = asyncio.run(detect(HA(ents, states), shared))
    assert found["pv_power"] == {"entity_id": "sensor.myinv_x", "source": "shared:newinv"}
    assert found["battery_soc"] == {"entity_id": "sensor.myinv_bat_level", "source": "shared:newinv"}
    assert "pv_power" not in asyncio.run(detect(HA(ents, states)))

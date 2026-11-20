"""A charger without live power (Monta): its kWh counter can be chosen, and the power is worked out from how fast it rises."""

import json

from energy_pilot import chargers, energyrate
from energy_pilot.overview import Overview, _watts


class HA:
    def __init__(self, states):
        self.states = states
        self.config = {"time_zone": "UTC"}


def st(v, unit="kWh"):
    return {"state": str(v), "attributes": {"unit_of_measurement": unit, "state_class": "total_increasing"}}


def test_power_from_counter():
    energyrate._SEEN.clear()
    e = "sensor.monta_charged_total"
    assert energyrate.watts(e, st(100.0), now=0) == 0.0  # first look: nothing known yet
    assert energyrate.watts(e, st(100.0), now=60) == 0.0
    assert round(energyrate.watts(e, st(100.5), now=240)) == 7500  # 0.5 kWh in 4 min (from the first look) = 7.5 kW
    assert round(energyrate.watts(e, st(101.0), now=480)) == 7500
    assert round(energyrate.watts(e, st(101.0), now=700)) == 7500  # between updates: the last power holds
    assert energyrate.watts(e, st(101.0), now=480 + 700) == 0.0  # stopped rising: not charging


def test_counter_reset_and_jump():
    energyrate._SEEN.clear()
    e = "sensor.x"
    energyrate.watts(e, st(50), now=0)
    assert energyrate.watts(e, st(2), now=60) == 0.0  # reset
    assert energyrate.watts(e, st(500), now=120) == 0.0  # impossible jump


def test_wh_and_overview_reader():
    energyrate._SEEN.clear()
    s = dict(st(1000, "Wh"), entity_id="sensor.c")
    assert _watts(s) == 0.0
    s2 = dict(st(1100, "Wh"), entity_id="sensor.c")
    assert _watts(s2) is not None
    assert _watts({"state": "2.5", "attributes": {"unit_of_measurement": "kW"}}) == 2500  # power sensors untouched


def test_extra_charger_counter():
    energyrate._SEEN.clear()
    states = {"sensor.c2": st(10)}
    assert chargers.read(states, {"power": "sensor.c2"})["power"] == 0.0


def test_counter_offered_only_for_charging_power(tmp_path):
    states = {
        "sensor.monta_charged_total": {"state": "123.4", "attributes": {"unit_of_measurement": "kWh", "state_class": "total_increasing"}},
        "sensor.monta_last_price": {"state": "3.4", "attributes": {"unit_of_measurement": "kWh"}},
        "sensor.house_power": {"state": "800", "attributes": {"unit_of_measurement": "W", "device_class": "power"}},
    }
    (tmp_path / "energy_pilot_settings.json").write_text(json.dumps({}))
    c = Overview(HA(states), tmp_path).candidates()
    ev = [r["entity_id"] for r in c["ev_power"]]
    assert "sensor.monta_charged_total" in ev
    assert "sensor.monta_last_price" not in ev  # no total: not a counter
    assert "sensor.monta_charged_total" not in [r["entity_id"] for r in c["house_power"]]

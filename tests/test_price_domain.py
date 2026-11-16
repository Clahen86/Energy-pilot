"""A price is never an update, a button or a switch - such a pick is passed over and not offered."""

import json

from energy_pilot.detect import NOT_HOME_BATTERY
from energy_pilot.overview import Overview


class HA:
    def __init__(self, states):
        self.states = states
        self.config = {"time_zone": "UTC"}


def test_update_entity_is_no_price(tmp_path):
    states = {
        "update.tibber_price_information_ratings_update": {"state": "off", "attributes": {}},
        "sensor.tibber_price": {"state": "0.31", "attributes": {"unit_of_measurement": "EUR/kWh"}},
    }
    (tmp_path / "energy_pilot_settings.json").write_text(json.dumps({"roles": {"price": "update.tibber_price_information_ratings_update"}}))
    o = Overview(HA(states), tmp_path)
    assert o.role("price") != "update.tibber_price_information_ratings_update"
    offered = [r["entity_id"] for r in o.candidates()["price"]]
    assert "update.tibber_price_information_ratings_update" not in offered
    assert "sensor.tibber_price" in offered


def test_octopus_car_level_is_no_house_battery():
    assert "octopus_energy" in NOT_HOME_BATTERY

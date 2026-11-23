"""A charger picked once (Settings > Car): its power, plug, charged energy and the car's level come from its own device."""

from energy_pilot.detect import charger_devices


def _st(cls=None, unit=None):
    return {"state": "0", "attributes": {k: v for k, v in (("device_class", cls), ("unit_of_measurement", unit)) if v}}


def test_evcc_loadpoint_and_not_its_site():
    ents = [{"entity_id": e, "platform": "evcc_intg", "device_id": d} for e, d in (
        ("sensor.evcc_garage_charge_power", "lp"), ("binary_sensor.evcc_garage_connected", "lp"),
        ("sensor.evcc_garage_charged_energy", "lp"), ("sensor.evcc_garage_vehicle_soc", "lp"),
        ("sensor.evcc_garage_charge_total_import", "lp"), ("sensor.evcc_garage_charge_remaining_energy", "lp"),
        ("sensor.evcc_garage_plan_time", "lp"), ("sensor.evcc_garage_effective_plan_time", "lp"),
        ("sensor.evcc_battery_power", "site"), ("sensor.evcc_grid_power", "site"))]
    states = {"sensor.evcc_garage_charge_power": _st("power", "kW"), "binary_sensor.evcc_garage_connected": _st(),
              "sensor.evcc_garage_charged_energy": _st("energy", "kWh"), "sensor.evcc_garage_vehicle_soc": _st(None, "%"),
              "sensor.evcc_garage_charge_total_import": _st("energy", "kWh"),
              "sensor.evcc_garage_charge_remaining_energy": _st(None, "kWh"),
              "sensor.evcc_garage_plan_time": _st("timestamp"), "sensor.evcc_garage_effective_plan_time": _st("timestamp"),
              "sensor.evcc_battery_power": _st("power", "W"), "sensor.evcc_grid_power": _st("power", "W")}
    found = charger_devices(ents, {"lp": {"name": "Garage"}, "site": {"name": "evcc"}}, states)
    assert found == [{"device_id": "lp", "name": "Garage", "platform": "evcc_intg", "roles": {
        "ev_power": "sensor.evcc_garage_charge_power", "ev_plug": "binary_sensor.evcc_garage_connected",
        "ev_session": "sensor.evcc_garage_charged_energy", "ev_soc": "sensor.evcc_garage_vehicle_soc",
        "ev_ready": "sensor.evcc_garage_effective_plan_time"}}]


def test_easee_and_a_cars_own_plug_is_never_taken():
    ents = [{"entity_id": "sensor.easee_power", "platform": "easee", "device_id": "e1"},
            {"entity_id": "binary_sensor.easee_cable_locked", "platform": "easee", "device_id": "e1"},
            {"entity_id": "sensor.easee_session_energy", "platform": "easee", "device_id": "e1"},
            {"entity_id": "binary_sensor.passat_stik", "platform": "volkswagencarnet", "device_id": "car"}]
    states = {"sensor.easee_power": _st("power", "kW"), "binary_sensor.easee_cable_locked": _st(),
              "sensor.easee_session_energy": _st("energy", "kWh"), "binary_sensor.passat_stik": _st("plug")}
    found = charger_devices(ents, {"e1": {"name": "Easee", "name_by_user": "Carport"}}, states)
    assert len(found) == 1 and found[0]["name"] == "Carport"
    assert found[0]["roles"] == {"ev_power": "sensor.easee_power", "ev_plug": "binary_sensor.easee_cable_locked",
                                 "ev_session": "sensor.easee_session_energy"}


def test_nothing_without_a_charger():
    assert charger_devices([{"entity_id": "sensor.x_power", "platform": "growatt", "device_id": "g"}], {}, {"sensor.x_power": _st("power", "W")}) == []

from energy_pilot import evsoc
from energy_pilot.detect import car_socs


def ent(eid, platform, device="car1"):
    return {"entity_id": eid, "platform": platform, "device_id": device}


def st(v, dc="battery", name=None):
    return {"state": str(v), "attributes": {"unit_of_measurement": "%", "device_class": dc, "friendly_name": name or ""}}


DEVICES = [{"id": "car1", "manufacturer": "Kia", "model": "EV6"}, {"id": "phone", "manufacturer": "Apple", "model": "iPhone"},
           {"id": "house", "manufacturer": "Growatt", "model": "SPH"}, {"id": "tag", "manufacturer": "Tesla", "model": "Key"}]


def test_the_cars_driving_battery_is_found_and_none_of_the_look_alikes():
    entities = [ent("sensor.ev6_ev_battery_level", "kia_uvo"), ent("sensor.ev6_car_battery_level", "kia_uvo"),  # 12 V
                ent("sensor.ev6_charge_limit_ac", "kia_uvo"), ent("sensor.iphone_battery_level", "mobile_app", "phone"),
                ent("sensor.growatt_sph_battery_state_of_charge", "growatt_server", "house"),
                ent("sensor.door_sensor_battery", "zha", "tag"), ent("sensor.ev6_tyre_pressure_battery", "kia_uvo")]
    states = {"sensor.ev6_ev_battery_level": st(64), "sensor.ev6_car_battery_level": st(88), "sensor.ev6_charge_limit_ac": st(80),
              "sensor.iphone_battery_level": st(50), "sensor.growatt_sph_battery_state_of_charge": st(90),
              "sensor.door_sensor_battery": st(100), "sensor.ev6_tyre_pressure_battery": st(70)}
    assert [c["entity_id"] for c in car_socs(entities, DEVICES, states)] == ["sensor.ev6_ev_battery_level"]


def test_a_plain_battery_named_sensor_is_not_taken_ford_12v():
    entities = [ent("sensor.fordpass_battery", "fordpass")]
    assert car_socs(entities, DEVICES, {"sensor.fordpass_battery": st(80)}) == []


def test_a_sleeping_car_still_counts_and_tesla_is_found():
    entities = [ent("sensor.model_y_battery_level", "tesla_fleet"), ent("sensor.model_y_charge_limit", "tesla_fleet")]
    states = {"sensor.model_y_battery_level": {"state": "unavailable", "attributes": {"unit_of_measurement": "%", "device_class": "battery"}},
              "sensor.model_y_charge_limit": st(80)}
    assert [c["entity_id"] for c in car_socs(entities, DEVICES, states)] == ["sensor.model_y_battery_level"]


def test_need_target_and_trip():
    assert evsoc.target({}) == 80 and evsoc.target({"ev_target": 70}) == 70 and evsoc.target({"ev_target": 70, "ev_trip": True}) == 100
    assert round(evsoc.need_kwh(60, 80, 60), 1) == round(20 / 100 * 60 / 0.9, 1)
    assert evsoc.need_kwh(85, 80, 60) == 0
    assert evsoc.trip_done({"ev_trip": True}, False, True, 98) and not evsoc.trip_done({"ev_trip": True}, False, True, 70)


def test_the_car_size_is_learned_from_a_charge():
    state = {}
    cs = evsoc.CarSize(state)
    for soc, kwh in ((40, 0.0), (50, 7.0), (60, 14.0)):  # 20 % for 14 kWh from the charger
        cs.see(True, soc, kwh)
    cs.see(False, None, None)
    for soc, kwh in ((30, 0.0), (50, 14.0)):
        cs.see(True, soc, kwh)
    size, how = cs.kwh({})
    assert how == "learned" and abs(size - 63.0) < 0.5
    assert cs.kwh({"ev_battery_kwh": 77})[0] == 77


def test_a_car_percentage_named_otherwise_is_offered_never_picked():
    from energy_pilot.detect import car_socs

    ents = [{"entity_id": "sensor.skoda_enyaq_charge_state_percent", "platform": "myskoda", "device_id": "sk"},
            {"entity_id": "sensor.home_minimum_state_of_charge", "platform": "myskoda", "device_id": "sk"}]
    st = {"sensor.skoda_enyaq_charge_state_percent": {"state": "64", "attributes": {"unit_of_measurement": "%"}},
          "sensor.home_minimum_state_of_charge": {"state": "50", "attributes": {"unit_of_measurement": "%"}}}
    got = car_socs(ents, [{"id": "sk", "manufacturer": "Škoda"}], st)
    assert [g["entity_id"] for g in got] == ["sensor.skoda_enyaq_charge_state_percent"] and got[0]["score"] == -5

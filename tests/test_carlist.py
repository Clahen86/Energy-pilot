"""More cars than chargers: which car is in the charger - its own sensor, picked by hand, or the same as last time."""

from energy_pilot import carlist, chargers

CARS = [{"id": "a", "name": "ID.3", "soc": "sensor.id3_soc", "plug": "binary_sensor.id3_plug", "car_kwh": 58, "target": 80},
        {"id": "b", "name": "Passat GTE", "plug": "binary_sensor.gte_plug", "car_kwh": 13, "need_kwh": 10},
        {"id": "c", "name": "Old Zoe", "car_kwh": 40, "need_kwh": 25}]


def st(**kw):
    return {"cars": CARS, **kw}


def on(*ids):
    return {e: {"state": "on"} for e in ids}


def test_no_list_changes_nothing():
    assert carlist.assign({}, {}, {"car": True}) is None
    assert carlist.car_in({}, "car") is None
    conf = {"power": "x", "need_kwh": 20}
    assert carlist.merged({}, "car2", conf) is conf


def test_the_car_that_says_plugged_in():
    states = {**on("binary_sensor.gte_plug"), "binary_sensor.id3_plug": {"state": "off"}}
    assert carlist.assign(st(), states, {"car": True})["car_in"] == {"car": "b"}


def test_car_saying_unplugged_is_not_it():
    states = {"binary_sensor.id3_plug": {"state": "off"}, "binary_sensor.gte_plug": {"state": "off"}}
    assert carlist.assign(st(car_in={"car": "a"}), states, {"car": True})["car_in"] == {"car": "c"}  # the one without sensor


def test_same_as_last_when_it_cant_tell():
    states = {"binary_sensor.id3_plug": {"state": "unavailable"}, "binary_sensor.gte_plug": {"state": "unavailable"}}
    assert carlist.assign(st(car_in={"car": "b"}), states, {"car": True}) is None


def test_picked_by_hand_stays_until_unplugged():
    s = st(**carlist.pick(st(), "car", "c"))
    assert s["car_in"] == {"car": "c"} and s["car_in_manual"] == {"car": True}
    assert carlist.assign(s, on("binary_sensor.id3_plug"), {"car": True}) is None  # the hand-picked car stays
    s.update(carlist.assign(s, {}, {"car": False}))
    assert s["car_in_manual"] == {}
    assert carlist.assign(s, on("binary_sensor.id3_plug"), {"car": True})["car_in"] == {"car": "a"}


def test_two_chargers_two_cars():
    states = on("binary_sensor.id3_plug", "binary_sensor.gte_plug")
    s = st(car_in={"car": "a"})
    got = carlist.assign(s, states, {"car": True, "car2": True})
    assert got is None or got["car_in"]["car"] != got["car_in"]["car2"]
    s.update(got or {})
    assert s["car_in"]["car"] != s["car_in"].get("car2", "x")


def test_extra_charger_takes_the_cars_settings():
    s = st(car_in={"car2": "b"})
    m = carlist.merged(s, "car2", {"power": "x", "need_kwh": 40, "soc": "sensor.other"})
    assert m["need_kwh"] == 10 and m["soc"] is None and m["car_name"] == "Passat GTE"
    assert chargers.need(m, {"session_kwh": 4}) == 6.0
    s2 = st(car_in={"car2": "a"})
    m2 = carlist.merged(s2, "car2", {"power": "x"})
    assert round(chargers.need(m2, {"soc": 62.0}), 1) == 11.6  # 18 % of 58 kWh / 0.9


def test_view_and_update():
    s = st(car_in={"car": "b"})
    v = carlist.view(s, "car")
    assert v["name"] == "Passat GTE" and not v["manual"] and len(v["choices"]) == 3
    assert carlist.update_car(s, "a", {"trip": True})["cars"][0]["trip"] is True


def test_charger_one_shows_the_car_in_it(tmp_path):
    import json

    from energy_pilot.overview import Overview

    class HA:
        states = {"sensor.p": {"state": "0", "attributes": {"unit_of_measurement": "W"}}, "binary_sensor.plug": {"state": "on"},
                  "sensor.id3_soc": {"state": "40"}, "binary_sensor.id3_plug": {"state": "on"}}
        config = {"time_zone": "UTC"}

    (tmp_path / "energy_pilot_settings.json").write_text(json.dumps(
        {"roles": {"ev_power": "sensor.p", "ev_plug": "binary_sensor.plug"}, "ev_target": 90, "ev_need_kwh": 33,
         "cars": CARS, "car_in": {"car": "a"}}))
    ev = Overview(HA(), tmp_path).ev()
    assert ev["soc"] == 40 and ev["soc_known"] and ev["target"] == 80 and ev["car_kwh"] == 58 and ev["car"]["name"] == "ID.3"
    (tmp_path / "energy_pilot_settings.json").write_text(json.dumps(
        {"roles": {"ev_power": "sensor.p", "ev_plug": "binary_sensor.plug"}, "cars": CARS, "car_in": {"car": "b"}}))
    ev = Overview(HA(), tmp_path).ev()
    assert ev["soc"] is None and not ev["soc_known"] and ev["cap"] == 10 and ev["car"]["name"] == "Passat GTE"
    # a car without a ready time still shows the field, so one can be set (DK user, 2026-11-27: it was gone)
    assert ev["ready"] == ""


LEARNED = [{"id": "e", "name": "EV", "kw_seen": [10.8, 11.0, 10.9]}, {"id": "h", "name": "PHEV", "kw_seen": [3.6, 3.7, 3.6]}]


def test_power_tells_the_cars_apart():
    assert carlist.by_power(LEARNED, ["e", "h"], 3.65) == "h"
    assert carlist.by_power(LEARNED, ["e", "h"], 10.5) == "e"
    assert carlist.by_power(LEARNED, ["e", "h"], 7.0) is None  # neither


def test_no_guess_before_three_charges_or_when_close():
    few = [LEARNED[0], {"id": "h", "kw_seen": [3.6, 3.7]}]
    assert carlist.by_power(few, ["e", "h"], 3.65) is None
    close = [LEARNED[0], {"id": "x", "kw_seen": [10.0, 10.1, 10.0]}]
    assert carlist.by_power(close, ["e", "x"], 10.9) is None


def test_assign_by_power_when_no_sensor():
    s = {"cars": LEARNED, "car_in": {"car": "e"}}
    assert carlist.assign(s, {}, {"car": True}, {"car": 3.7})["car_in"] == {"car": "h"}
    assert carlist.assign(s, {}, {"car": True}, {"car": None}) is None  # not charging yet: the same as last


def test_power_watch_and_learning():
    w = carlist.PowerWatch()
    for _ in range(12):
        w.see({"car": True}, {"car": 3700})
    assert w.now_kw("car") == 3.7
    done = w.see({"car": False}, {"car": 0})
    assert done == {"car": 3.7}
    s = {"cars": [{"id": "h", "kw_seen": []}, {"id": "e"}], "car_in": {"car": "h"}}
    assert carlist.learn(s, done) is None  # not sure which car it was: nothing learned
    s["car_in_manual"] = {"car": True}
    assert carlist.learn(s, done)["cars"][0]["kw_seen"] == [3.7]


def test_sensor_makes_it_sure():
    got = carlist.assign(st(), on("binary_sensor.gte_plug"), {"car": True})
    assert got["car_in_sure"] == {"car": True}
    s = st(**got)
    assert carlist.assign(s, on("binary_sensor.gte_plug"), {"car": False})["car_in_sure"] == {}

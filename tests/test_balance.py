"""The meters must add up: sun + grid = house + battery (charging +). When they don't for two hours, the one change
that makes them add up is made (autofix.py) - found in a Fox ESS house whose "house" was the grid's buying sensor."""

import math
import time

from energy_pilot.autofix import judge


def day(n=120):
    """Minutes of a sunny day with a battery: (sun, house, battery charging +), grid = the rest (buying +)."""
    out = []
    for i in range(n):
        house = 300 + 250 * (i % 7 == 0) + 2200 * (i % 23 == 0)  # a kettle now and then
        if i < 40:  # the sunny afternoon: the battery charges, the rest is sold
            sun, batt = 2700 + 600 * math.sin(i / 9), 800.0
        else:  # the evening: the battery runs the house
            sun, batt = 0.0, -min(house, 3000)
        grid = house + batt - sun
        out.append({"pv": sun, "grid": grid, "batt": batt, "house": house, "real_house": house})
    return out


def test_meters_that_add_up_are_left_alone():
    assert judge(day(), {}, {"grid_power", "battery_power"})["ok"] is True


def test_the_house_read_from_the_grids_buying_sensor():
    rows = day()
    for s in rows:
        s["c"] = {"sensor.foxess_load_power": s["real_house"], "sensor.kettle_power": 2200 if s["house"] > 2000 else 0}
        s["house"] = max(0.0, s["grid"])  # "grid consumption power": what is bought, never what is sold
    res = judge(rows, {"house_power": ["sensor.foxess_load_power", "sensor.kettle_power"]}, {"grid_power", "battery_power"})
    assert res["ok"] is False
    assert res["fix"] == {"role": "house_power", "kind": "entity", "entity": "sensor.foxess_load_power", "share": 1.0}


def test_a_battery_read_the_wrong_way_round():
    rows = day()
    for s in rows:
        s["batt"] = -s["batt"]
    res = judge(rows, {}, {"grid_power", "battery_power"})
    assert res["fix"]["role"] == "battery_power" and res["fix"]["kind"] == "sign"
    assert judge(rows, {}, {"grid_power"}).get("fix") is None  # a charge/discharge pair is never turned


def test_a_quiet_sensor_never_stands_in_for_the_grid():
    rows = day()
    for s in rows:
        s["grid"] = 5000.0  # a wrong grid sensor
        s["c"] = {"sensor.idle_plug_power": 0.0}
    res = judge(rows, {"grid_power": ["sensor.idle_plug_power"]}, set())
    assert res["ok"] is False and "fix" not in res


def test_too_little_seen():
    rows = day(30)
    assert judge(rows, {}, set())["ok"] is None
    for s in rows:
        s.update(pv=0.0, grid=100.0, batt=0.0, house=100.0)  # a quiet night: nothing to judge by
    assert judge(day(0) + rows * 4, {}, set())["ok"] is None


def test_noise_and_losses_are_no_reason_to_change_anything():
    import random

    rnd = random.Random(7)
    rows = day()
    for s in rows:  # inverter losses (the sun's DC is more than what comes out) and sensors read a moment apart
        s["pv"] *= 1.05
        for k in ("grid", "batt", "house"):
            s[k] *= 1 + rnd.uniform(-0.04, 0.04)
        s["c"] = {"sensor.other_power": s["house"] * 1.5}
    res = judge(rows, {"house_power": ["sensor.other_power"]}, {"grid_power", "battery_power"})
    assert res["ok"] is True


def test_the_fox_house_is_mended_and_can_be_undone():
    from types import SimpleNamespace

    from energy_pilot import autofix as A

    rows = day()
    roles = {"house_power": "sensor.foxess_grid_consumption_power", "grid_power": "sensor.grid"}
    store = {"roles": dict(roles)}
    st = {"sensor.foxess_load_power": {"state": "0", "attributes": {"device_class": "power", "unit_of_measurement": "W"}}}
    now = {"i": 0}

    def flow():
        s = rows[now["i"]]
        return {"pv": s["pv"], "grid": s["grid"], "battery": s["batt"], "house": max(0.0, s["grid"]), "ev": 0}

    o = SimpleNamespace(settings=store, save=lambda d: store.update(d), flow=flow, grid_pair=lambda: None,
                        battery_pair=lambda: ("c", "d"), grid_sign=lambda: 1, battery_sign=lambda: 1,
                        candidates=lambda: {"house_power": [{"entity_id": "sensor.foxess_load_power", "guess": True}]},
                        ha=SimpleNamespace(states=st, config={"country": "GB"}))
    a = A.AutoFix(o)
    t = time.time()
    for i, s in enumerate(rows):
        now["i"] = i
        st["sensor.foxess_load_power"]["state"] = str(s["real_house"])
        a.balance(st, roles, t + 60 * i)
    assert store["roles"]["house_power"] == "sensor.foxess_load_power"
    assert store["autofix_log"][-1]["what"] == "balance"
    a.undo("balance:house_power")
    assert store["roles"]["house_power"] == "sensor.foxess_grid_consumption_power" and "balance:house_power" in store["autofix_ignore"]

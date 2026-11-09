"""More than one charger: found by itself, each car planned on its own, all within the main fuse."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from energy_pilot import chargers
from energy_pilot.engine import Engine, Hour

T0 = datetime(2026, 11, 8, 22, tzinfo=ZoneInfo("Europe/Berlin"))


def s(v, unit=None, name=None):
    return {"state": str(v), "attributes": {"unit_of_measurement": unit, "friendly_name": name}}


STATES = {
    "sensor.keba_p30_charging_power": s(0, "kW", "KEBA 1"),
    "binary_sensor.keba_p30_plug": s("on"),
    "sensor.keba_p30_charging_power_2": s(3.7, "kW", "KEBA 2 Charging power"),
    "binary_sensor.keba_p30_plug_2": s("on"),
    "sensor.keba_p30_session_energy_2": s(4.0, "kWh"),
    "sensor.heat_pump_power": s(900, "W"),
}


def test_finds_the_second_keba():
    found = chargers.find(STATES, "sensor.keba_p30_charging_power", "binary_sensor.keba_p30_plug", [], [])
    assert found == [{"power": "sensor.keba_p30_charging_power_2", "plug": "binary_sensor.keba_p30_plug_2",
                      "session": "sensor.keba_p30_session_energy_2", "name": "KEBA 2 Charging power"}]
    assert chargers.find(STATES, "sensor.keba_p30_charging_power", "binary_sensor.keba_p30_plug", [], ["sensor.keba_p30_charging_power_2"]) == []


def test_read():
    r = chargers.read(STATES, {"power": "sensor.keba_p30_charging_power_2", "plug": "binary_sensor.keba_p30_plug_2",
                                "session": "sensor.keba_p30_session_energy_2"})
    assert r == {"name": "", "power": 3700.0, "plug": True, "session_kwh": 4.0}


def test_second_car_stays_under_the_fuse():
    # cheapest 01-03; car 1 already takes 01-03 at 11 kW, the fuse is 17 kW -> car 2 (11 kW) must go elsewhere
    hours = [Hour(T0 + timedelta(hours=i), 0.1 if 3 <= i <= 5 else 0.3, 0.0, 1.0, 0.0) for i in range(10)]
    settings = {"import_limit_kw": 17, "charger_kw": 11, "chargers": [{"power": "x", "charger_kw": 11, "need_kwh": 11}]}
    eng = SimpleNamespace(ov=SimpleNamespace(settings=settings), quiet_hours=lambda w: [])
    car1 = {"set": {hours[3].start, hours[4].start, hours[5].start}}
    out = Engine._more_cars(eng, hours, T0, {"cars": [{"plug": True, "session_kwh": 0}]}, car1, 60)
    chosen = [datetime.fromisoformat(t) for t in out[0]["hours"]]
    assert len(chosen) == 1 and chosen[0] not in car1["set"]


def test_second_car_takes_the_cheapest_when_there_is_room():
    hours = [Hour(T0 + timedelta(hours=i), 0.1 if i == 4 else 0.3, 0.0, 1.0, 0.0) for i in range(10)]
    settings = {"import_limit_kw": 25, "charger_kw": 11, "chargers": [{"power": "x", "charger_kw": 11, "need_kwh": 11}]}
    eng = SimpleNamespace(ov=SimpleNamespace(settings=settings), quiet_hours=lambda w: [])
    out = Engine._more_cars(eng, hours, T0, {"cars": [{"plug": True, "session_kwh": 0}]}, {"set": {hours[4].start}}, 60)
    assert [datetime.fromisoformat(t) for t in out[0]["hours"]] == [hours[4].start]


def _ctl(settings, flow, cars_plan):
    from energy_pilot.control import Controller

    c = Controller.__new__(Controller)
    c.ha = SimpleNamespace(config={"time_zone": "Europe/Berlin"})
    c.ov = SimpleNamespace(settings=settings, role=lambda r: None)
    c._sun_on_more, c.more_why = {}, {}
    return c._more_intents(flow, {"cars": cars_plan}, {"intent": "charge", "ctx": {"current": 16}})


def test_second_charger_is_turned_down_before_the_first():
    # 25 kW fuse, house buys 5 kW, charger 1 takes 16 A x 3 x 230 V = 11.04 kW -> 8.96 kW left = 12 A for charger 2
    st = {"import_limit_kw": 25, "charger_kw": 11, "chargers": [{"power": "x", "charger_kw": 11, "now": True}]}
    flow = {"pv": 0, "house": 5000, "battery": 0, "grid": 5000 + 11000 + 11000, "ev": 22000,
            "cars": [{"plug": True, "power": 11000}]}
    want = _ctl(st, flow, [{"hours": [], "need_kwh": 10}])["car2"]
    assert want == {"intent": "charge", "ctx": {"current": 12}}


def test_second_charger_stops_when_no_room():
    st = {"import_limit_kw": 17, "charger_kw": 11, "chargers": [{"power": "x", "charger_kw": 11, "now": True}]}
    flow = {"pv": 0, "house": 5000, "battery": 0, "grid": 16000, "ev": 11000, "cars": [{"plug": True, "power": 0}]}
    assert _ctl(st, flow, [{"hours": [], "need_kwh": 10}])["car2"]["intent"] == "stop"


def test_second_charger_charges_in_its_planned_hour():
    now = datetime.now(ZoneInfo("Europe/Berlin")).replace(minute=0, second=0, microsecond=0)
    st = {"charger_kw": 11, "chargers": [{"power": "x", "charger_kw": 7.4}]}
    flow = {"pv": 0, "house": 500, "battery": 0, "grid": 500, "ev": 0, "cars": [{"plug": True, "power": 0}]}
    want = _ctl(st, flow, [{"hours": [now.isoformat()], "need_kwh": 10, "slot_min": 60}])["car2"]
    assert want["intent"] == "charge" and want["ctx"]["current"] == 32

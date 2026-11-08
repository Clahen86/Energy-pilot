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

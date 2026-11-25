"""Extra cars like the first one: their own battery level, a target in %, the next trip - and the buttons from the
card and the companion (/api/charger)."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from energy_pilot import chargers
from energy_pilot.engine import Engine, Hour

T0 = datetime(2026, 11, 8, 22, tzinfo=ZoneInfo("Europe/Berlin"))


def test_reads_the_cars_level():
    states = {"sensor.p": {"state": "0", "attributes": {"unit_of_measurement": "W"}}, "binary_sensor.plug": {"state": "on"},
              "sensor.id3_battery": {"state": "45"}}
    r = chargers.read(states, {"power": "sensor.p", "plug": "binary_sensor.plug", "soc": "sensor.id3_battery"})
    assert r["soc"] == 45.0


def test_need_from_level_and_target():
    c = {"soc": "sensor.x", "target": 80, "car_kwh": 18}  # a plug-in hybrid: 18 kWh
    assert round(chargers.need(c, {"soc": 30.0, "session_kwh": 5}), 1) == 10.0  # 50 % of 18 kWh / 0.9
    assert round(chargers.need({**c, "trip": True}, {"soc": 30.0}), 1) == 14.0  # 100 % for the trip
    assert chargers.need(c, {"soc": 90.0}) == 0.0


def test_need_without_level_is_at_most_less_session():
    assert chargers.need({"need_kwh": 20}, {"session_kwh": 5}) == 15.0
    assert chargers.need({}, {}) == 20.0


def test_car_size_guarded():
    assert chargers.car_kwh({"car_kwh": 77}) == 77.0
    assert chargers.car_kwh({"car_kwh": "x"}) == chargers.car_kwh({}) == 60.0


def test_plan_uses_the_level():
    hours = [Hour(T0 + timedelta(hours=i), 0.1 if i in (3, 4) else 0.3, 0.0, 1.0, 0.0) for i in range(10)]
    settings = {"chargers": [{"power": "x", "charger_kw": 7.4, "need_kwh": 50, "soc": "sensor.lvl", "target": 80, "car_kwh": 18}]}
    eng = SimpleNamespace(ov=SimpleNamespace(settings=settings), quiet_hours=lambda w: [])
    out = Engine._more_cars(eng, hours, T0, {"cars": [{"plug": True, "session_kwh": 0, "soc": 60.0}]}, None, 60)
    assert out[0]["need_kwh"] == 4.0  # 20 % of 18 kWh / 0.9 - not the 50 kWh "at most"
    assert [datetime.fromisoformat(t) for t in out[0]["hours"]] == [hours[3].start]

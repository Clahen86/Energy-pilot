"""The battery's grid charge gives way to what the house really uses now - the import limit holds live, not only in the plan."""

from types import SimpleNamespace

from energy_pilot import control as C
from energy_pilot.engine import Battery


def _ctl(house_w, limit=6.0):
    c = C.Controller.__new__(C.Controller)
    bat = Battery(capacity_kwh=20, max_charge_kw=5, max_discharge_kw=5, min_soc=10, import_limit_kw=limit)
    c.engine = SimpleNamespace(result={"battery": {"steps": [{"t": "2026-11-27T02:00:00+00:00", "action": "charge_grid", "soc": 90, "grid": 6.0}],
                                                   "slot_min": 60, "target": 90}}, settings=lambda: bat, ev_in_house=lambda: False)
    c.ov = SimpleNamespace(flow=lambda: {"soc": 40, "house": house_w, "pv": 0, "ev": 0}, settings={"inverter_profile": "victron"},
                           sell_sun=lambda: False, ev=lambda: None)
    c.ha = SimpleNamespace(config={"time_zone": "UTC"})
    c.car_why = ""
    c.bat_parts = lambda: []
    return c


def test_charge_backs_off_when_the_house_takes_more():
    assert _ctl(1000).intents()["battery"]["ctx"]["power_w"] == 4800  # 6 kW - 1 kW - margin
    assert _ctl(300).intents()["battery"]["ctx"]["power_w"] == 5000  # room for the full charge


def test_no_room_at_all_waits():
    assert _ctl(5800).intents()["battery"]["intent"] == "hold"

"""The last check before a battery order is written: within the battery's own limits, whatever the plan says."""

from datetime import datetime, timezone
from types import SimpleNamespace

from energy_pilot import control as C
from energy_pilot.engine import Battery


def _ctl(soc=50, room=None, **bat):
    c = C.Controller.__new__(C.Controller)
    b = Battery(**{"capacity_kwh": 10, "max_charge_kw": 5, "max_discharge_kw": 4, "min_soc": 10, **bat})
    c.engine = SimpleNamespace(settings=lambda: b)
    c.ov = SimpleNamespace(flow=lambda: {"soc": soc, "battery": 0}, phase_room_a=lambda: room)
    c.ha = SimpleNamespace(config={"time_zone": "UTC"})
    return c


def _w(intent, **ctx):
    return {"intent": intent, "ctx": {"power_w": 3000, "rate": 60, **ctx}}


def test_a_sound_order_goes_through():
    assert C.Controller._guard(_ctl(), "battery", _w("charge"))["intent"] == "charge"
    assert C.Controller._guard(_ctl(export=True), "battery", _w("export"))["intent"] == "export"


def test_the_power_is_kept_within_the_battery():
    w = C.Controller._guard(_ctl(), "battery", _w("charge", power_w=99000, rate=400))
    assert w["ctx"]["power_w"] == 5000 and w["ctx"]["rate"] == 100
    w = C.Controller._guard(_ctl(export=True, export_limit_kw=2), "battery", _w("export", power_w=9000, export_w=6000))
    assert w["ctx"]["power_w"] == 4000 and w["ctx"]["export_w"] == 2000


def test_orders_that_break_a_rule_become_normal():
    hour = datetime.now(timezone.utc).hour
    cases = [
        (_ctl(grid_charge=False), "charge"),
        (_ctl(quiet=frozenset({hour})), "charge"),
        (_ctl(soc=96, grid_max_soc=90), "charge"),
        (_ctl(room=-3.0), "charge"),  # over the fuse already, without the battery
        (_ctl(export=False), "export"),
        (_ctl(soc=10, export=True), "export"),
        (_ctl(soc=None), "hold"),
        (_ctl(), "explode"),
    ]
    for c, intent in cases:
        assert C.Controller._guard(c, "battery", _w(intent))["intent"] == "normal", intent

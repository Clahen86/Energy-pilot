"""Sell the sun instead of storing it: a hold with a planned surplus keeps the sun out of the battery."""

from types import SimpleNamespace

from energy_pilot import control as C
from energy_pilot.engine import Battery


def _ctl(sell_sun=True, grid=-0.8, action="hold", profile="victron"):
    c = C.Controller.__new__(C.Controller)
    bat = Battery(capacity_kwh=10, max_charge_kw=5, max_discharge_kw=5, min_soc=10)
    c.engine = SimpleNamespace(result={"battery": {"steps": [{"t": "2026-11-17T12:00:00+00:00", "action": action, "soc": 50, "grid": grid}],
                                                   "slot_min": 60, "target": 50}}, settings=lambda: bat)
    settings = {"sell_sun": sell_sun, "inverter_profile": profile}
    c.ov = SimpleNamespace(flow=lambda: {"soc": 50, "house": 400, "pv": 1500}, settings=settings, sell_sun=lambda: sell_sun,
                           ev=lambda: None)
    c.ha = SimpleNamespace(config={"time_zone": "UTC"})
    c.car_why = ""
    c.bat_parts = lambda: []
    return c


def test_hold_with_surplus_blocks_charging():
    ctx = _ctl().intents()["battery"]["ctx"]
    assert ctx["max_charge_w"] == 0 and ctx.get("sell_sun")


def test_off_or_not_selling_keeps_charging():
    assert _ctl(sell_sun=False).intents()["battery"]["ctx"]["max_charge_w"] == 5000
    assert _ctl(grid=0.3).intents()["battery"]["ctx"]["max_charge_w"] == 5000  # no surplus sold
    assert _ctl(action="charge_sun").intents()["battery"]["ctx"]["max_charge_w"] == 5000


def test_only_where_the_hold_sets_the_limit():
    assert _ctl(profile="victron").can_block_sun()
    assert not _ctl(profile="solarman").can_block_sun()

"""A plan that ran out never drives the battery: no prices, or a planning that stopped, runs the battery as normal."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from energy_pilot import control as C
from energy_pilot.engine import Battery, Engine


def _old_plan(hours_ago=5):
    t = (datetime.now(ZoneInfo("UTC")) - timedelta(hours=hours_ago)).replace(minute=0, second=0, microsecond=0)
    return {"battery": {"steps": [{"t": t.isoformat(), "action": "charge_grid", "soc": 90, "grid": 4.0}],
                        "slot_min": 60, "target": 90}}


def _ctl(engine, price_none):
    bat = Battery(capacity_kwh=10, max_charge_kw=5, max_discharge_kw=5, min_soc=10)
    engine.settings = lambda: bat
    c = C.Controller.__new__(C.Controller)
    c.engine = engine
    c.ov = SimpleNamespace(flow=lambda: {"soc": 40}, settings={"inverter_profile": "growatt"},
                           price_info={"none": price_none}, sell_sun=lambda: False, ev=lambda: None)
    c.ha = SimpleNamespace(config={"time_zone": "UTC"})
    c.car_why = ""
    c.bat_parts = lambda: []
    return c


def test_no_prices_drops_the_last_plan():
    e = Engine.__new__(Engine)
    e.result = _old_plan()
    e.ov = SimpleNamespace(plan=lambda: {"hours": []}, settings={})
    e.ha = SimpleNamespace(config={"time_zone": "UTC"})
    e.weather = None
    assert e.run() is None
    assert e.result is None
    assert _ctl(e, price_none=True).intents()["battery"]["intent"] == "normal"


def test_a_plan_that_ran_out_runs_as_normal_even_with_prices():
    # The planning stopped (an error) while the prices are there: the old grid charge isn't followed on.
    e = SimpleNamespace(result=_old_plan())
    assert _ctl(e, price_none=False).intents()["battery"]["intent"] == "normal"


def test_the_running_step_is_still_followed():
    e = SimpleNamespace(result=_old_plan(hours_ago=0))
    assert _ctl(e, price_none=False).intents()["battery"]["intent"] == "charge"

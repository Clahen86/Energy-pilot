"""Sell the sun instead of storing it: a hold with a planned surplus keeps the sun out of the battery."""

from datetime import datetime, timedelta, timezone

# The step began 58 minutes ago: still running, with the 5-minute floor on the time left (a plan that ran out
# is no longer followed - control._live_steps).
T0 = (datetime.now(timezone.utc) - timedelta(minutes=58)).isoformat()
T9 = (datetime.fromisoformat(T0) + timedelta(hours=9)).isoformat()
from types import SimpleNamespace

from energy_pilot import control as C
from energy_pilot.engine import Battery


def _ctl(sell_sun=True, grid=-0.8, action="hold", profile="victron"):
    c = C.Controller.__new__(C.Controller)
    bat = Battery(capacity_kwh=10, max_charge_kw=5, max_discharge_kw=5, min_soc=10)
    c.engine = SimpleNamespace(result={"battery": {"steps": [{"t": T0, "action": action, "soc": 50, "grid": grid}],
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


def test_hold_only_for_the_sun_runs_normal():
    # the plan held because the sun was to cover the house: the battery covers what it doesn't (FR report, 100 % and buying)
    assert _ctl(sell_sun=False, grid=-0.1).intents()["battery"]["intent"] == "normal"
    assert _ctl(sell_sun=False, grid=0.0).intents()["battery"]["intent"] == "normal"
    # a hold that buys from the grid to keep the battery for later stays a hold
    assert _ctl(sell_sun=False, grid=0.6).intents()["battery"]["intent"] == "hold"
    # selling the sun instead of storing it stays a hold
    assert _ctl(sell_sun=True, grid=-0.8).intents()["battery"]["intent"] == "hold"


def test_no_prices_means_the_battery_runs_as_normal():
    # NL tester, 2026-11-20: no prices anywhere, so no plan - the battery mustn't stay in its last order (a grid charge).
    c = _ctl()
    c.engine.result = None
    c.ov.price_info = {"none": True}
    assert c.intents()["battery"]["intent"] == "normal"
    c.ov.price_info = {}
    assert "battery" not in c.intents()  # no plan yet for another reason (just started): nothing is sent


KOSTAL = ["switch.plenticore_l_g3_charge_start", "switch.plenticore_l_g3_discharge_start",
          "switch.plenticore_l_g3_block_charge", "switch.plenticore_l_g3_block_discharge",
          "number.plenticore_l_g3_set_charge_rate", "number.plenticore_l_g3_set_discharge_rate"]


def _kostal_calls(sell_sun):
    c = _ctl(sell_sun=sell_sun, grid=-0.8 if sell_sun else 0.6, profile="kostal_modbus_control")
    c.entities = {"battery": KOSTAL}
    c.ha.states = {}
    want = c.intents()["battery"]
    return want["intent"], [(x["service"], x["data"]["entity_id"]) for x in c.calls("battery", want)]


def test_kostal_sells_the_sun_with_block_charge():
    # Its switches can't be on together, and Block Discharge lets the sun fill the battery: selling the sun while
    # holding takes Block Charge instead - the battery stays where the plan has it.
    c = _ctl(profile="kostal_modbus_control")
    assert c.can_block_sun()
    intent, calls = _kostal_calls(sell_sun=True)
    assert intent == "hold" and calls == [("turn_on", "switch.plenticore_l_g3_block_charge")]


def test_kostal_plain_hold_still_blocks_discharge():
    intent, calls = _kostal_calls(sell_sun=False)  # holding for later while buying: the sun may fill it
    assert intent == "hold" and calls == [("turn_on", "switch.plenticore_l_g3_block_discharge")]


def _with_hours(c, sell_now, later_price, later_grid=0.6):
    # Thursday 13:00 in the user's plan: a surplus smaller than one 2 % step shows as a hold that sells; the plan buys
    # later in the evening.
    c.engine.result["battery"]["steps"].append(
        {"t": T9, "action": "discharge", "soc": 10, "grid": later_grid})
    hr = lambda t: datetime.fromisoformat(t).replace(minute=0, second=0, microsecond=0).isoformat()  # noqa: E731
    c.ov.plan = lambda: {"hours": [{"t": hr(T0), "price": 3.1, "sell": sell_now},
                                   {"t": hr(T9), "price": later_price, "sell": 1.8}]}
    return c


def test_sun_stored_when_it_saves_more_than_selling_earns():
    c = _with_hours(_ctl(), sell_now=2.145, later_price=2.909)  # stored: 0.92 * 2.909 = 2.68 > 2.145
    want = c.intents()["battery"]
    assert want["intent"] == "normal" and not want["ctx"].get("sell_sun")


def test_sun_sold_when_selling_earns_more():
    c = _with_hours(_ctl(), sell_now=2.9, later_price=2.909)  # 2.9 > 0.92 * 2.909 = 2.68
    assert c.intents()["battery"]["ctx"].get("sell_sun")


def test_sun_sold_when_nothing_is_bought_later():
    c = _with_hours(_ctl(), sell_now=2.145, later_price=2.909, later_grid=0.0)
    assert c.intents()["battery"]["ctx"].get("sell_sun")

"""While the battery charges from the grid, small changes in the power and the stop level aren't written again -
fewer writes to the inverter. A change of intent or a bigger step goes through at once."""

import asyncio

from energy_pilot import control as C

from test_drift import FakeHA, ctl_with


def _charge(soc, target, rate):
    return {"intent": "charge", "ctx": {"soc": soc, "target": target, "rate": rate, "power_w": rate * 30, "power_kw": rate * 0.03}}


def test_small_steps_are_kept_back():
    prev = _charge(30, 95, 100)
    w = C.steady(prev, _charge(31, 93, 97))
    assert w["ctx"]["rate"] == 100 and w["ctx"]["power_w"] == 3000 and w["ctx"]["target"] == 95 and w["ctx"]["soc"] == 31
    w = C.steady(prev, _charge(31, 95, 80))
    assert w["ctx"]["rate"] == 80 and w["ctx"]["power_w"] == 2400  # a real change goes through
    w = C.steady(prev, _charge(31, 89, 100))
    assert w["ctx"]["target"] == 89  # more than 3 % on the stop level
    w = C.steady(_charge(30, 25, 100), _charge(24, 27, 100))
    assert w["ctx"]["target"] == 27  # close to the old stop level: it would stop too early, so the new one


def test_a_new_top_power_goes_through():
    # the user turned the battery's charge power down from 7 to 5 kW while it charged at full: the rate stayed 100 %
    prev = _charge(30, 95, 100)
    prev["ctx"].update(max_charge_w=7000, power_w=7000, charge_a=140)
    new = _charge(31, 95, 100)
    new["ctx"].update(max_charge_w=5000, power_w=5000, charge_a=100)
    w = C.steady(prev, new)
    assert w["ctx"]["power_w"] == 5000 and w["ctx"]["charge_a"] == 100


def test_only_while_charging_on_and_on():
    prev = _charge(30, 95, 100)
    hold = {"intent": "hold", "ctx": {"soc": 31, "target": 93, "rate": 97}}
    assert C.steady(prev, hold) is hold
    assert C.steady(None, _charge(31, 93, 97))["ctx"]["rate"] == 97
    assert C.steady(hold, _charge(31, 93, 97))["ctx"]["rate"] == 97


def _ctl(ha):
    c = ctl_with(ha)
    c.calls = lambda part, w: ([
        {"domain": "number", "service": "set_value", "data": {"entity_id": "number.rate", "value": w["ctx"]["rate"]}},
        {"domain": "number", "service": "set_value", "data": {"entity_id": "number.stop", "value": w["ctx"]["target"]}},
        {"domain": "select", "service": "select_option", "data": {"entity_id": "select.mode", "option": "Battery first"}}]
        if w["intent"] == "charge" else
        [{"domain": "select", "service": "select_option", "data": {"entity_id": "select.mode", "option": "Load first"}}])
    return c


def test_a_charging_hour_like_the_growatt_writes_far_less(monkeypatch):
    async def fast(_):
        return None
    monkeypatch.setattr(C.asyncio, "sleep", fast)
    ha = FakeHA({"number.rate": {"state": "0"}, "number.stop": {"state": "0"}, "select.mode": {"state": "Load first"}})
    c = _ctl(ha)
    # every 5 minutes: the level rises, the power wobbles 97/100 and the stop level creeps 89-95 (21 November)
    for soc, target, rate in [(23, 89, 97), (23, 89, 100), (25, 91, 100), (27, 95, 97), (27, 95, 100), (30, 95, 100),
                              (32, 95, 97), (32, 95, 100), (33, 93, 97), (35, 95, 100)]:
        c.intents = (lambda w: lambda: {"battery": w})(_charge(soc, target, rate))
        asyncio.run(c.tick())
    assert ha.sent.count("number.rate") == 1 and ha.sent.count("number.stop") == 2  # 89 -> 95 is a real step
    assert len(c.log["battery"]) == 2
    c.intents = lambda: {"battery": {"intent": "hold", "ctx": {"soc": 35}}}
    asyncio.run(c.tick())
    assert ha.states["select.mode"]["state"] == "Load first"  # a change of intent goes at once

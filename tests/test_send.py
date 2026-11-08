"""Only values that aren't set are written, and a value that didn't stick is written once more."""

import asyncio

from energy_pilot import control as C


class FakeHA:
    def __init__(self, states, drop_first=()):
        self.states, self.calls, self.drop = states, [], set(drop_first)

    async def call_service(self, domain, service, data):
        self.calls.append(data["entity_id"])
        e = data["entity_id"]
        if e in self.drop:
            self.drop.discard(e)  # Solarman drops the first write
            return
        self.states[e] = {"state": str(data.get("option", data.get("value")))}


def run(ha, calls):
    ctl = C.Controller.__new__(C.Controller)
    ctl.ha = ha
    return asyncio.run(ctl._send(calls))


def test_skips_set_values_and_resends_dropped(monkeypatch):
    async def fast(_):
        return None
    monkeypatch.setattr(C.asyncio, "sleep", fast)
    ha = FakeHA({"number.max": {"state": "3000"}, "number.min": {"state": "0"}, "select.mode": {"state": "Self Use"}},
                drop_first={"select.mode"})
    calls = [{"domain": "number", "service": "set_value", "data": {"entity_id": "number.max", "value": 3000}},
             {"domain": "number", "service": "set_value", "data": {"entity_id": "number.min", "value": 0}},
             {"domain": "select", "service": "select_option", "data": {"entity_id": "select.mode", "option": "Passive"}}]
    assert run(ha, calls) == "ok"
    assert ha.calls == ["select.mode", "select.mode"]

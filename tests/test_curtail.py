"""Stop selling at negative prices: only in control, the owner's value remembered and put back afterwards."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from energy_pilot.curtail import Curtail, candidates


class HA:
    def __init__(self):
        self.states = {"number.growatt_export_limit": {"state": "100", "attributes": {"unit_of_measurement": "%"}},
                       "sensor.other": {"state": "1"}}
        self.calls = []

    async def call_service(self, dom, svc, data):
        self.calls.append((dom, svc, data))
        self.states[data["entity_id"]]["state"] = str(data.get("value"))


class Ov:
    def __init__(self, ha, sell):
        self.ha = ha
        self.settings = {"curtail": {"on": True, "entity": "number.growatt_export_limit", "value": 0}}
        self.engine = SimpleNamespace(tz=timezone.utc, sell_prices=lambda: {datetime(2020, 1, 1, tzinfo=timezone.utc): sell[0]},
                                      sell_at=lambda p, w, f: list(p.values())[0])

    def save(self, d):
        self.settings.update(d)

    def plan(self):
        return {}


def run(mode, prices):
    ha, sell = HA(), [0.0]
    ov = Ov(ha, sell)
    c = Curtail(ha, ov, SimpleNamespace(mode=lambda p: mode))
    for p in prices:
        sell[0] = p
        asyncio.run(c.tick())
    return ha, ov, c


def test_found():
    assert [x["entity_id"] for x in candidates(HA().states)] == ["number.growatt_export_limit"]


def test_stops_and_puts_back():
    ha, ov, _ = run("control", [0.5, -0.1, -0.2, 0.3])
    assert [c[2]["value"] for c in ha.calls] == [0, 100]
    assert ha.states["number.growatt_export_limit"]["state"] == "100"
    assert ov.settings["curtail_saved"] is None


def test_shadow_does_nothing():
    ha, _, c = run("shadow", [-0.5])
    assert ha.calls == [] and c.last["want"] is True


def test_off_does_nothing():
    ha, sell = HA(), [-1.0]
    ov = Ov(ha, sell)
    ov.settings["curtail"]["on"] = False
    asyncio.run(Curtail(ha, ov, SimpleNamespace(mode=lambda p: "control")).tick())
    assert ha.calls == []


def growatt_ha():
    ha = HA()
    ha.states = {"select.growatt_sph_export_limiter": {"state": "Disabled", "attributes": {"options": ["Disabled", "Enabled"]}},
                 "number.growatt_sph_export_power_rate": {"state": "100", "attributes": {}},
                 "select.growatt_sph_work_mode_priority": {"state": "Load first", "attributes": {}}}

    async def call(dom, svc, data):
        ha.calls.append((dom, svc, data))
        ha.states[data["entity_id"]]["state"] = str(data.get("value", data.get("option")))
    ha.call_service = call
    return ha


def test_chosen_from_brand():
    ha = growatt_ha()
    c = Curtail(ha, Ov(ha, [0.0]), SimpleNamespace(mode=lambda p: "shadow", profile_key=lambda p: "growatt"))
    sg = c.suggest()
    assert sg["entity"] == "select.growatt_sph_export_limiter" and sg["value"] == "Enabled"
    assert sg["extra"] == [["number.growatt_sph_export_power_rate", "0"]]
    assert "select.growatt_sph_work_mode_priority" not in [x["entity_id"] for x in candidates(ha.states)]


def test_turned_on_fills_in_and_both_are_set_and_put_back():
    ha, sell = growatt_ha(), [-0.2]
    ov = Ov(ha, sell)
    ov.settings["curtail"] = {"on": True}
    c = Curtail(ha, ov, SimpleNamespace(mode=lambda p: "control", profile_key=lambda p: "growatt"))
    asyncio.run(c.tick())
    assert ha.states["select.growatt_sph_export_limiter"]["state"] == "Enabled"
    assert ha.states["number.growatt_sph_export_power_rate"]["state"] == "0"
    sell[0] = 0.5
    asyncio.run(c.tick())
    assert ha.states["select.growatt_sph_export_limiter"]["state"] == "Disabled"
    assert ha.states["number.growatt_sph_export_power_rate"]["state"] == "100"


def _tested(grid_before, grid_after, monkeypatch):
    import energy_pilot.curtail as cm

    async def fast(_s):
        return None
    monkeypatch.setattr(cm, "TEST_S", 10)
    monkeypatch.setattr("asyncio.sleep", fast)
    ha = growatt_ha()
    ov = Ov(ha, [0.5])
    ov.settings["curtail"] = {"on": True, "entity": "select.growatt_sph_export_limiter", "value": "Enabled",
                              "extra": [["number.growatt_sph_export_power_rate", "0"]]}
    grids = iter([grid_before] + [grid_after] * 10)
    ov.flow = lambda: {"grid": next(grids)}
    res = asyncio.run(Curtail(ha, ov, SimpleNamespace(mode=lambda p: "shadow")).test())
    return res, ha, ov


def test_test_ok_and_put_back(monkeypatch):
    res, ha, ov = _tested(-2000, -10, monkeypatch)
    assert res["result"] == "ok" and ov.settings["curtail_test"]["result"] == "ok"
    assert ha.states["select.growatt_sph_export_limiter"]["state"] == "Disabled"


def test_test_failed(monkeypatch):
    assert _tested(-2000, -1900, monkeypatch)[0]["result"] == "failed"


def test_test_no_sun(monkeypatch):
    res, ha, _ = _tested(300, 300, monkeypatch)
    assert res["result"] == "no_sun" and ha.calls == []

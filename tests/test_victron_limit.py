"""Victron's persistent ESS limit at 0 is pointed out (never changed); "normal" in the self-test needs the battery to
really cover the house; the headline says "planned" when the battery stands still while the house buys."""

from types import SimpleNamespace

from energy_pilot import checks, selftest
from energy_pilot.engine import Battery
from energy_pilot.overview import Overview


def test_limit_found_only_at_zero():
    assert checks.victron_limit({"number.gx_device_ess_max_inverter_power_limit": {"state": "0"}}) == "number.gx_device_ess_max_inverter_power_limit"
    assert checks.victron_limit({"number.gx_device_ess_max_inverter_power_limit": {"state": "-1"}}) is None
    assert checks.victron_limit({"number.ess_maximum_discharge_power": {"state": "0"}}) is None  # the Hub4 override: ours
    ov = SimpleNamespace(settings={}, flow=lambda: {"soc": 50}, role=lambda r: None,
                         ha=SimpleNamespace(states={"number.gx_device_ess_max_inverter_power_limit": {"state": "0"}}))
    eng = SimpleNamespace(ov=ov, batt_learn=SimpleNamespace(capacity=lambda: None), ev_detected=None, grid_peak=SimpleNamespace(kw=lambda: None))
    assert [c["key"] for c in checks.run(eng, [], Battery(), None, 0.0)] == ["victron_limit"]


def test_normal_fails_when_idle_while_buying():
    assert selftest._expect("normal", {"battery": -900, "grid": 50, "soc": 60}, {}) is True
    assert selftest._expect("normal", {"battery": 0, "grid": 1200, "soc": 60}, {}) is False  # held back by something
    assert selftest._expect("normal", {"battery": 0, "grid": 1200, "soc": 12}, {}) is True  # empty: nothing to give


def test_headline_planned_after_five_minutes(monkeypatch):
    import time as T
    o = Overview.__new__(Overview)
    o.flow = lambda: {"battery": 10, "grid": 800, "soc": 60}
    now = [1000.0]
    monkeypatch.setattr(T, "time", lambda: now[0])
    assert o._not_discharging("FREE_DISCHARGE") is False
    now[0] += 301
    assert o._not_discharging("FREE_DISCHARGE") is True
    o.flow = lambda: {"battery": -1500, "grid": 50, "soc": 60}
    assert o._not_discharging("FREE_DISCHARGE") is False  # it discharges after all
    assert o._not_discharging("FREE_HOLD") is False

"""Victron/Deye: the owner's own setting is remembered before selling and put back after."""

from types import SimpleNamespace

from energy_pilot import control as C


def ctl(states, key="victron"):
    c = C.Controller.__new__(C.Controller)
    store = {}
    c.ha = SimpleNamespace(states=states)
    c.ov = SimpleNamespace(settings=store, save=lambda d: store.update(d))
    c.profile_key = lambda: key
    c._pool = lambda: list(states)
    return c, store


def test_victron_setpoint_is_put_back():
    states = {"number.victron_ess_grid_setpoint": {"state": "50"}}
    c, store = ctl(states)
    assert c._restore("battery", "export") == []
    assert store["restore_values"] == {"number.victron_ess_grid_setpoint": "50"}
    states["number.victron_ess_grid_setpoint"]["state"] = "-3000"  # selling
    c._restore("battery", "export")
    assert store["restore_values"]["number.victron_ess_grid_setpoint"] == "50"  # the owner's, not the selling one
    back = c._restore("battery", "normal")
    assert back == [{"domain": "number", "service": "set_value", "data": {"entity_id": "number.victron_ess_grid_setpoint", "value": 50}}]


def test_deye_work_mode_is_put_back():
    states = {"select.deye_work_mode": {"state": "Zero Export To CT"}, "select.deye_energy_pattern": {"state": "Load First"},
              "number.deye_export_surplus_power": {"state": "4000"}}
    c, store = ctl(states, "solarman")
    c._restore("battery", "export")
    assert store["restore_values"] == {"select.deye_work_mode": "Zero Export To CT", "number.deye_export_surplus_power": "4000"}

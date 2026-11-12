"""Victron/Deye: the owner's own setting is remembered before selling and put back after."""

from types import SimpleNamespace

from energy_pilot import control as C


def ctl(states, key="victron"):
    c = C.Controller.__new__(C.Controller)
    store = {}
    c.ha = SimpleNamespace(states=states)
    c.ov = SimpleNamespace(settings=store, save=lambda d: store.update(d))
    c.profile_key = lambda *a: key
    c._pool = lambda *a: list(states)
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


def test_a_selling_setpoint_is_never_kept_as_the_owners():
    """A user saw his Victron go on selling after the plan stopped: the 'own' value saved was a selling one."""
    states = {"number.ess_ac_grid_setpoint": {"state": "-3800"}}  # left selling by an older version
    c, store = ctl(states)
    c._restore("battery", "export")
    assert store["restore_values"] == {"number.ess_ac_grid_setpoint": "0"}
    back = c._restore("battery", "normal")
    assert back == [{"domain": "number", "service": "set_value", "data": {"entity_id": "number.ess_ac_grid_setpoint", "value": 0}}]
    store.clear()  # nothing remembered at all, still selling: put to 0 anyway
    back = c._restore("battery", "normal")
    assert back[0]["data"]["value"] == 0
    states["number.ess_ac_grid_setpoint"]["state"] = "40"
    assert c._restore("battery", "normal") == []  # the owner's own positive value is left alone


def test_growatt_lets_go_of_the_selling_slot():
    """Selling turns on grid-first slot 1 for the whole day: normal and hold must turn it off again."""
    from energy_pilot import adapters

    for intent in ("normal", "hold"):
        steps = adapters.PROFILES["growatt"][intent]
        assert any(p.endswith("grid_first_slot_1_enabled$") and kind == "off" for p, kind, _ in steps)
    assert any(p.endswith("grid_first_slot_1_enabled$") for p in adapters.PROFILES["growatt"]["optional"])

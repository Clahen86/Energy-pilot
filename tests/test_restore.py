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


def test_deye_grid_charge_current_follows_the_plan_and_is_put_back():
    """A tester's Deye charged with 10 kW from the grid while the setting said 5: the current was never set."""
    from energy_pilot import adapters

    ents = ["number.deye_inverter_battery_grid_charging_current", "number.deye_inverter_battery_generator_charging_current",
            "select.deye_inverter_program_1_charging"]
    calls = adapters.resolve(adapters.PROFILES["solarman"]["charge"], ents, {"target": 80, "charge_a": 86, "grid_charge": True})
    cur = [c for c in calls if c["data"]["entity_id"].endswith("grid_charging_current")]
    assert cur == [{"domain": "number", "service": "set_value", "data": {"entity_id": ents[0], "value": 86}}]
    assert "{charge_a}" in str(adapters.PROFILES["deye_esphome"]["charge"])
    # without the amps (another make's ctx) the step is left out, not an error
    assert not [c for c in adapters.resolve(adapters.PROFILES["solarman"]["charge"], ents, {"target": 80})
                if c["data"]["entity_id"] == ents[0]]

    states = {ents[0]: {"state": "185"}, "select.deye_work_mode": {"state": "Zero Export To CT"}}
    c, store = ctl(states, "solarman")
    c.is_battery = lambda part: True
    assert c._restore("battery", "charge") == []  # remembered, not put back while charging
    assert store["restore_values"] == {ents[0]: "185"}
    states[ents[0]]["state"] = "86"
    c._restore("battery", "charge")
    assert store["restore_values"][ents[0]] == "185"  # the owner's, not EP's
    c._restore("battery", "export")  # charging → selling: the current goes back, the work mode is remembered
    assert store["restore_values"]["select.deye_work_mode"] == "Zero Export To CT"
    back = c._restore("battery", "hold")
    assert {"domain": "number", "service": "set_value", "data": {"entity_id": ents[0], "value": 185}} in back
    assert {"domain": "select", "service": "select_option", "data": {"entity_id": "select.deye_work_mode", "option": "Zero Export To CT"}} in back

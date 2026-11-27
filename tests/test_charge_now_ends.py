""""Charge now" is for one charge: it goes off when the car is unplugged, so the next plug-in follows the plan."""

import asyncio
from types import SimpleNamespace

from energy_pilot.evsoc import end_charge_now, unplugged


def _ov(settings, roles, states):
    calls = []

    async def call(domain, service, data):
        calls.append((domain, service, data["entity_id"]))
        states[data["entity_id"]] = {"state": "off"}

    ov = SimpleNamespace(settings=settings, role=lambda r: roles.get(r), save=settings.update)
    return ov, SimpleNamespace(states=states, call_service=call), calls


def test_unplugged_is_only_a_real_unplug():
    assert unplugged("off") and unplugged("Available") and unplugged("disconnected")
    assert not unplugged("on") and not unplugged("unavailable") and not unplugged("unknown") and not unplugged(None)


def test_the_helper_goes_off_when_the_car_leaves():
    roles = {"ev_plug": "binary_sensor.keba_plug", "ev_manual": "input_boolean.bil_lad_manuelt"}
    states = {"binary_sensor.keba_plug": {"state": "off"}, "input_boolean.bil_lad_manuelt": {"state": "on"}}
    ov, ha, calls = _ov({}, roles, states)
    asyncio.run(end_charge_now(ov, ha, True, {}))
    assert calls == [("input_boolean", "turn_off", "input_boolean.bil_lad_manuelt")]


def test_not_while_in_or_on_a_sensor_blip():
    roles = {"ev_plug": "binary_sensor.keba_plug", "ev_manual": "input_boolean.bil_lad_manuelt"}
    for plug, was in (("on", True), ("unavailable", True), ("off", False)):
        states = {"binary_sensor.keba_plug": {"state": plug}, "input_boolean.bil_lad_manuelt": {"state": "on"}}
        ov, ha, calls = _ov({}, roles, states)
        asyncio.run(end_charge_now(ov, ha, was, {}))
        assert calls == [], (plug, was)


def test_the_panel_setting_and_an_extra_charger_too():
    st = {"ev_now": True, "chargers": [{"plug": "sensor.easee_status", "power": "sensor.easee_power", "now": True}]}
    states = {"binary_sensor.keba_plug": {"state": "off"}, "sensor.easee_status": {"state": "disconnected"}}
    ov, ha, calls = _ov(st, {"ev_plug": "binary_sensor.keba_plug"}, states)
    asyncio.run(end_charge_now(ov, ha, True, {0: True}))
    assert st["ev_now"] is False and st["chargers"][0]["now"] is False and calls == []

"""Settings → Car → Control: only switches that have to do with charging, and plain on/off switches work."""

from energy_pilot import adapters, chargers
from energy_pilot.carspeed import decide


def reg(eid, dev=None, **kw):
    return {"entity_id": eid, "device_id": dev, **kw}


def st(*ids):
    return {e: {"state": "off", "attributes": {"friendly_name": e.split(".", 1)[1].replace("_", " ").title()}} for e in ids}


REG = [
    reg("sensor.commando_power", "shelly"), reg("switch.commando", "shelly"),          # Shelly measuring the portable charger
    reg("switch.shelly_led_indicator", "shelly"),
    reg("switch.portable_evse_switch", "tuya1"), reg("select.portable_evse_charge_current", "tuya1"),
    reg("switch.portable_evse_child_lock", "tuya1"),
    reg("switch.aircon_power", "tuya2"), reg("switch.cat_litter", "tuya3"),          # other Tuya things
    reg("switch.growatt_battery_charge", "inv"), reg("switch.growatt_ac_charge", "inv"),  # the inverter
    reg("switch.kitchen_light", "hue"), reg("switch.tesla_charger", "tesla"), reg("switch.tesla_sentry_mode", "tesla"),
    reg("switch.old_charger", "x", disabled_by="user"),
]
STATES = st(*[r["entity_id"] for r in REG])
DEVS = {"tuya1": {"manufacturer": "Tuya", "model": "Portable EV Charger"}}


def opts(anchors=("sensor.commando_power",), skip=("inv",)):
    return [o["entity_id"] for o in chargers.switch_options(REG, DEVS, STATES, list(anchors), set(skip))]


def test_only_charging_switches():
    o = opts()
    assert o[0] == "switch.commando"  # on the device that measures the charger: first
    assert set(o) == {"switch.commando", "switch.portable_evse_switch", "switch.tesla_charger"}


def test_never_inverter_light_lock_or_disabled():
    o = opts(anchors=(), skip=())
    for bad in ("switch.growatt_battery_charge", "switch.growatt_ac_charge", "switch.kitchen_light", "switch.aircon_power",
                "switch.cat_litter", "switch.portable_evse_child_lock", "switch.shelly_led_indicator", "switch.tesla_sentry_mode",
                "switch.old_charger"):
        assert bad not in o


def test_lone_switch_on_own_device():
    assert adapters.charger_switch(["switch.commando"], lone_ok=True) == "switch.commando"
    assert adapters.charger_switch(["switch.commando"], lone_ok=False) is None
    assert adapters.charger_switch(["switch.a", "switch.b"], lone_ok=True) is None


def test_chosen_switch_and_current_select():
    states = {"select.portable_evse_charge_current": {"state": "16A", "attributes": {"options": ["6A", "10A", "16A", "32A"]}}}
    calls = adapters.charger_calls("charge", ["select.portable_evse_charge_current", "switch.portable_evse_switch"], None, 10,
                                   states=states, switch="switch.portable_evse_switch")
    assert calls[0]["data"]["option"] == "10A" and calls[1]["service"] == "turn_on"
    stop = adapters.charger_calls("stop", ["switch.commando"], None, 16, switch="switch.commando")
    assert stop == [{"domain": "switch", "service": "turn_off", "data": {"entity_id": "switch.commando"}}]


def test_onoff_waits_for_full_power_of_sun():
    s = {"charger_kw": 3.7, "charger_phases": 1, "onoff": True}
    flow = {"plug": True, "pv": 3000, "house": 500, "battery": 0, "ev": 0}  # 2.5 kW over: enough for 6 A, not 16 A
    assert decide(flow, s, False, False, 10, False)["charge"] is False
    assert decide(flow, {**s, "onoff": False}, False, False, 10, False)["charge"] is True
    flow["pv"] = 5000
    d = decide(flow, s, False, False, 10, False)
    assert d["charge"] is True and d["current"] == 16

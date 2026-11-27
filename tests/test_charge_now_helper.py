""""Charge now" from the owner's own helper (an input_boolean set as ev_manual): the charger starts, not only the panel."""

from test_import_limit_live import _ctl


def _car(manual):
    c = _ctl(500, limit=None)
    c.ov.flow = lambda: {"soc": 50, "house": 500, "pv": 0, "ev": 0.0, "plug": True, "grid": 500.0, "battery": 0.0}
    c.ov.ev = lambda: {"manual": manual, "target": 80}  # what the panel shows - the helper is on
    c.ov.role = lambda r: None
    c.engine.power_tariff = lambda: None
    c.engine.result["car"] = {"hours": [], "slot_min": 60, "need_kwh": 20}
    c.onoff = lambda part: False
    c._sun_on = False
    return c


def test_charge_now_from_the_helper_starts_the_car():
    assert c_intent(_car(True)) == "charge"
    assert c_intent(_car(False)) == "stop"


def c_intent(c):
    return c.intents()["car"]["intent"]

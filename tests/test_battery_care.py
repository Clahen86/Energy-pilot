"""Spare the battery or the most saved: the share of the worked-out wear a move must pay for. An own wear is kept."""

from types import SimpleNamespace

from energy_pilot.engine import Engine


def eng(settings):
    e = Engine.__new__(Engine)
    e.ov = SimpleNamespace(settings=settings)
    e.ha = SimpleNamespace(config={"currency": "DKK"})
    e.batt_learn = SimpleNamespace(capacity=lambda: 12.1)
    e.battery_type = lambda: {"type": "lfp"}
    e._guess_capacity = lambda: None
    return e


def test_care_scales_the_worked_out_wear():
    assert eng({}).wear() == 0.133
    assert eng({"battery_care": "balanced"}).wear() == 0.067
    assert eng({"battery_care": "most"}).wear() == 0.027
    assert eng({"battery_care": "most"}).wear(own=False) == 0.133  # what it would be, shown in the settings
    assert eng({"battery_care": "most", "battery_wear": 0.2}).wear() == 0.2  # the user's own number wins

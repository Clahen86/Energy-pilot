"""A grid meter that counts buying as negative (Solis/SolaX PCC) is found from the house's balance, or set by hand."""

from types import SimpleNamespace

from energy_pilot.overview import Overview


def ov(settings=None):
    o = Overview.__new__(Overview)
    o.settings, o.engine = settings or {}, SimpleNamespace(ev_in_house=lambda: False)
    return o


def test_buying_counted_negative_is_found():
    o = ov()
    for _ in range(10):
        o._watch_grid(-340, 350, 0, 0, 0)  # house 350 W, no sun, battery resting: the grid gives 340 W
    assert o.grid_sign_found() == -1 and o.grid_sign() == -1


def test_normal_meter_and_unclear_cases():
    o = ov()
    for _ in range(10):
        o._watch_grid(900, 1000, 100, 0, 0)
        o._watch_grid(2000, 1000, 100, 3000, 0)  # battery working: no vote
    assert o.grid_sign_found() == 1
    assert ov({"grid_sign": -1}).grid_sign() == -1
    assert ov().grid_sign() == 1  # nothing seen yet


def test_goodwe_grid_is_plus_when_selling():
    """No house sensor to find it from: GoodWe's meter is known to count selling as plus."""
    from types import SimpleNamespace

    from energy_pilot.overview import Overview

    ov = Overview.__new__(Overview)
    ov.settings = {}
    ov.role = lambda r: "sensor.goodwe_active_power" if r == "grid_power" else None
    ov.controller = SimpleNamespace(_ent_reg={"sensor.goodwe_active_power": {"platform": "goodwe"}})
    assert ov.grid_sign() == -1
    ov.settings = {"grid_sign": 1}  # the user's own choice wins
    assert ov.grid_sign() == 1

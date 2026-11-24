"""Wallbox "Ready" = no car (its switch is unavailable then); a battery resting at the user's own floor isn't a fault."""
from energy_pilot import chargers
from energy_pilot.selftest import _expect


def test_wallbox_ready_and_locked_are_not_plugged():
    for s in ("Ready", "Locked", "no_ev_connected", "Disconnected"):
        assert chargers.is_plugged(s) is False, s


def test_plugged_states_still_plugged():
    for s in ("on", "Charging", "Paused", "Waiting for car demand", "ready_to_charge", "Locked, car connected", "plugged_in"):
        assert chargers.is_plugged(s) is True, s


def test_normal_resting_at_own_floor_is_ok():
    f = {"battery": 0, "grid": 1500, "soc": 31}
    assert _expect("normal", f, {"min_soc": 30}) is True
    assert _expect("normal", f, {"min_soc": 10}) is False  # with charge left it should cover the house

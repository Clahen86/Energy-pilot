"""evcc's plan time is a whole UTC timestamp: the page shows the car's "ready at" as local HH:MM (it showed "2026-")."""

from types import SimpleNamespace

from energy_pilot.overview import Overview


def _ov():
    return SimpleNamespace(ha=SimpleNamespace(config={"time_zone": "Europe/Copenhagen"}))


def test_a_timestamp_becomes_local_time():
    assert Overview._ready_hm(_ov(), "2026-11-24T06:30:00+00:00") == "07:30"


def test_a_helpers_time_is_left_as_it_is():
    assert Overview._ready_hm(_ov(), "07:30:00") == "07:30:00"
    assert Overview._ready_hm(_ov(), None) is None
    assert Overview._ready_hm(_ov(), "unknown") == "unknown"

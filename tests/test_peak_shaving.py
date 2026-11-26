from types import SimpleNamespace

from energy_pilot.checks import peak_shaving


def eng(states):
    return SimpleNamespace(ov=SimpleNamespace(ha=SimpleNamespace(states=states)))


def n(v, unit="W", mx=None):
    return {"state": str(v), "attributes": {"unit_of_measurement": unit, **({"max": mx} if mx else {})}}


def test_peak_shaving_below_the_fuse_is_offered_to_raise():
    b = SimpleNamespace(import_limit_kw=15)
    out = peak_shaving(eng({"number.deye_inverter_grid_peak_shaving_power": n(10000)}), b)
    assert out[0]["vals"] == {"inv": 10.0, "ep": 15.0}
    assert out[0]["fix"]["_set_number"] == {"entity_id": "number.deye_inverter_grid_peak_shaving_power", "value": 15000.0}


def test_off_or_high_enough_says_nothing():
    b = SimpleNamespace(import_limit_kw=15)
    assert peak_shaving(eng({"number.x_grid_peak_shaving": n(16000), "switch.x_grid_peak_shaving": {"state": "on"}}), b) == []
    assert peak_shaving(eng({"number.x_grid_peak_shaving": n(8000), "switch.x_grid_peak_shaving": {"state": "off"}}), b) == []
    assert peak_shaving(eng({"number.x_grid_peak_shaving": n(8000)}), SimpleNamespace(import_limit_kw=None)) == []


def test_capped_at_the_numbers_max():
    out = peak_shaving(eng({"number.x_grid_peak_shaving": n(8000, mx=12000)}), SimpleNamespace(import_limit_kw=15))
    assert out[0]["fix"]["_set_number"]["value"] == 12000.0

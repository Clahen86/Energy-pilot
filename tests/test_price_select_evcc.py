"""A price that is a select (Peak / Off Peak) is flagged; evcc's loadpoint is started and stopped by its mode."""

from types import SimpleNamespace

from energy_pilot import adapters, checks
from energy_pilot.engine import Battery


def engine(price_role):
    ov = SimpleNamespace(settings={}, flow=lambda: {"soc": 50}, role=lambda r: price_role if r == "price" else None)
    return SimpleNamespace(ov=ov, batt_learn=SimpleNamespace(capacity=lambda: None), ev_detected=None,
                           grid_peak=SimpleNamespace(kw=lambda: None))


def test_select_price_is_flagged():
    found = checks.run(engine("select.tou_current_rate"), [], Battery(), None, 0.0)
    assert [c["key"] for c in found] == ["price_text"] and found[0]["vals"]["e"] == "select.tou_current_rate"
    assert checks.run(engine("sensor.nordpool_kwh_dk1"), [], Battery(), None, 0.0) == []


def test_evcc_mode_now_and_off():
    ents = ["select.evcc_daheimlader_mode", "select.evcc_daheimlader_max_current", "number.evcc_daheimlader_limit_soc"]
    on = adapters.charger_calls("charge", ents, "evcc_intg", 16)
    off = adapters.charger_calls("stop", ents, "evcc_intg", 0)
    assert [(c["data"]["entity_id"], c["data"].get("option")) for c in on] == [("select.evcc_daheimlader_mode", "now")]
    assert [(c["data"]["entity_id"], c["data"].get("option")) for c in off] == [("select.evcc_daheimlader_mode", "off")]

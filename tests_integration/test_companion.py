import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from homeassistant.core import HomeAssistant

URL = "http://pilot:8099"
OV = {"decision": {"kind": "hold", "text": "Gemmer", "target": 60}, "price": {"now": 2.5}, "currency": "DKK", "flow": {"soc": 55},
      "ev": {"manual": False, "ready": "07:00:00", "cap": 20}, "engine": {"saving": 6.7, "learning": {"yesterday": {"saving": 3.2}}}}


async def test_entities(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.get(f"{URL}/api/overview", json=OV)
    aioclient_mock.get(f"{URL}/api/settings", json={"settings": {"style": "safe", "battery_min_soc": 30}})
    aioclient_mock.post(f"{URL}/api/ev", json={"ok": True})
    aioclient_mock.post(f"{URL}/api/shadow_all", json={"ok": True})
    e = MockConfigEntry(domain="energy_pilot", data={"url": URL}, unique_id="energy_pilot")
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    states = {s.entity_id: s.state for s in hass.states.async_all()}
    print(states)
    assert states["sensor.energipilot_decision"] == "hold"
    assert states["select.energipilot_style"] == "safe"
    assert states["time.energipilot_ready_at"] == "07:00:00"
    await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.energipilot_charge_now"}, blocking=True)
    assert any(c[0] == "POST" and str(c[1]).endswith("/api/ev") and c[2] == {"manual": True} for c in aioclient_mock.mock_calls)
    await hass.services.async_call("button", "press", {"entity_id": "button.energipilot_everything_back_to_shadow"}, blocking=True)

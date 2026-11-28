import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from homeassistant.core import HomeAssistant

URL = "http://pilot:8099"
OV = {"decision": {"kind": "hold", "text": "Gemmer", "target": 60}, "price": {"now": 2.5}, "currency": "DKK", "flow": {"soc": 55},
      "ev": {"manual": False, "ready": "07:00:00", "cap": 20}, "engine": {"saving": 6.7, "learning": {"yesterday": {"saving": 3.2}}}}


async def test_entities(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.get(f"{URL}/api/overview", json=OV)
    aioclient_mock.get(f"{URL}/api/settings", json={"settings": {"style": "safe", "battery_min_soc": 30}})
    aioclient_mock.get(f"{URL}/api/control", json={})
    aioclient_mock.post(f"{URL}/api/ev", json={"ok": True})
    aioclient_mock.post(f"{URL}/api/shadow_all", json={"ok": True})
    e = MockConfigEntry(domain="energy_pilot", data={"url": URL}, unique_id="energy_pilot")
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    states = {s.entity_id: s.state for s in hass.states.async_all()}
    print(states)
    assert states["sensor.energy_pilot_decision"] == "hold"
    assert states["select.energy_pilot_style"] == "safe"
    assert states["time.energy_pilot_ready_at"] == "07:00:00"
    await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.energy_pilot_charge_now"}, blocking=True)
    assert any(c[0] == "POST" and str(c[1]).endswith("/api/ev") and c[2] == {"manual": True} for c in aioclient_mock.mock_calls)
    await hass.services.async_call("button", "press", {"entity_id": "button.energy_pilot_everything_back_to_shadow"}, blocking=True)


async def test_tools_for_the_ai(hass: HomeAssistant, aioclient_mock):
    """The AI's tools: what Energy Pilot does now, the plan, the cheapest start for an appliance, the car, the savings."""
    from datetime import timedelta

    from homeassistant.helpers import llm
    from homeassistant.util import dt as dt_util

    start = dt_util.now().replace(minute=0, second=0, microsecond=0)
    prices = [3.0, 3.1, 2.0, 1.0, 1.1, 1.2, 2.5, 3.0]
    ov = {**OV, "flow": {"soc": 55, "pv": 0, "house": 600, "battery": -500, "grid": 0, "plug": True, "ev": 0},
          "decision": {"kind": "hold", "text": "Gemmer strømmen til i aften", "reason": "Dyrt kl. 17-20", "target": 60},
          "plan": {"hours": [{"t": (start + timedelta(hours=i)).isoformat(), "price": p, "sun": 0, "house": 0.5, "action": "hold", "soc": 55,
                              "car": i == 4} for i, p in enumerate(prices)], "cheapest": [(start + timedelta(hours=3)).isoformat()]},
          "ev": {"soc": 40, "target": 80, "ready": "07:00"}, "ledger": {"today": 4.2, "month": 120, "month_lo": 100, "month_hi": 140, "total": 900}}
    aioclient_mock.get(f"{URL}/api/overview", json=ov)
    aioclient_mock.get(f"{URL}/api/settings", json={"settings": {}})
    aioclient_mock.get(f"{URL}/api/control", json={})
    e = MockConfigEntry(domain="energy_pilot", data={"url": URL}, unique_id="energy_pilot")
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    ctx = llm.LLMContext(platform="test", context=None, language="da", assistant="conversation", device_id=None)
    api = await llm.async_get_api(hass, "energy_pilot", ctx)
    async def call(name, **args):
        r = await api.async_call_tool(llm.ToolInput(tool_name=name, tool_args=args))
        return getattr(r, "data", r)
    now = await call("energy_pilot_now")
    assert now["doing"] == "Gemmer strømmen til i aften" and now["battery_pct"] == 55 and now["price_now"] == 3.0
    best = await call("energy_pilot_best_start", appliance="dishwasher")
    assert best["run_hours"] == 3.0 and best["avg_price"] == 1.1 and best["saving_per_kwh"] > 1.5  # hours 3-5 at 1.0/1.1/1.2
    assert (await call("energy_pilot_plan", hours=4))["hours"][3]["price"] == 1.0
    car = await call("energy_pilot_car")
    assert car["plugged_in"] and car["level_pct"] == 40 and len(car["charges_at"]) == 1
    assert (await call("energy_pilot_savings"))["month_hi"] == 140
    assert await hass.config_entries.async_unload(e.entry_id)
    assert "energy_pilot" not in [a.id for a in llm.async_get_apis(hass)]


def test_best_start_never_bridges_a_gap_and_counts_only_the_sun_it_covers():
    from datetime import timedelta

    from homeassistant.util import dt as dt_util

    from custom_components.energy_pilot.llm_tools import best_start

    t0 = dt_util.now().replace(minute=0, second=0, microsecond=0)
    h = lambda i, p, **k: {"_t": t0 + timedelta(hours=i), "price": p, **k}  # noqa: E731
    gap = [h(0, 3.0), h(1, 0.5), h(3, 0.5), h(4, 3.0)]  # 2 o'clock missing
    got = best_start(gap, 2.0)
    assert got is None or got["avg_price"] > 0.5  # 1 and 3 o'clock are no unbroken two hours
    sunny = [h(0, 3.0, sun=1.0, house=0.0, sell=0.5), h(1, 3.0), h(2, 3.0)]
    car = best_start(sunny, 1.0, load_kw=7.0)
    assert car["avg_price"] > 2.5  # the sun covers a seventh of a car
    dish = best_start(sunny, 1.0, load_kw=0.7)
    assert dish["avg_price"] == 0.5 and dish["uses_own_sun"]
    half = best_start([h(0, 1.0), h(1, 1.0), h(2, 9.0)], 2.5)
    assert half["avg_price"] > 1.0  # 2.5 hours reach into the dear third hour

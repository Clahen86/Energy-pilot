"""Energy Pilot for your AI: tools an assistant (Google, ChatGPT, Claude, a local one) can look things up with.

Ask in your own words - "can I start the dishwasher now?", "why isn't the battery charging?", "how much did we save
this month?" - and the AI fetches the answer from Energy Pilot itself. Turned on once in the AI's settings
("Energy Pilot" under the tools it may use). Without an AI nothing changes. Only reads: no tool controls anything.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from homeassistant.util import dt as dt_util

try:  # newer Home Assistant
    import probatio as vol
except ImportError:  # pragma: no cover - older Home Assistant
    import voluptuous as vol

_LOGGER = logging.getLogger(__name__)
API_ID = "energy_pilot"
PROMPT = ("Energy Pilot plans and runs this home's battery, car charging and appliances by electricity price, sun and use. "
          "Use its tools for anything about electricity prices, when power is cheapest, when to start an appliance, the "
          "battery, solar, the car's charging, what Energy Pilot does now and why, and what it saved. Times are local. "
          "Prices are per kWh in the currency given. Answer short, in the user's language.")
# Typical running time, when the user doesn't say (hours)
RUNS = {"dishwasher": 3.0, "washing_machine": 2.0, "dryer": 2.0, "car": 4.0, "other": 2.0}
LOAD_KW = {"dishwasher": 0.7, "washing_machine": 0.8, "dryer": 1.5, "car": 7.0, "other": 1.0}  # about what it draws on average


def _pilot(hass: HomeAssistant) -> Any:
    from . import DOMAIN

    entries = [e for e in hass.config_entries.async_loaded_entries(DOMAIN) if getattr(e, "runtime_data", None)]
    return entries[0].runtime_data if entries else None


def _hm(t: str | None) -> str | None:
    if not t:
        return None
    try:
        return dt_util.as_local(dt_util.parse_datetime(t)).strftime("%a %H:%M")
    except (TypeError, ValueError, AttributeError):
        return None


def _hours(data: dict[str, Any]) -> list[dict[str, Any]]:
    """The plan's hours from now on (the hour now included)."""
    now = dt_util.now().replace(minute=0, second=0, microsecond=0)
    out = []
    for h in ((data.get("plan") or {}).get("hours") or []):
        try:
            t = dt_util.as_local(dt_util.parse_datetime(h["t"]))
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        if t >= now and isinstance(h.get("price"), (int, float)):
            out.append({**h, "_t": t})
    return out


def best_start(hours: list[dict[str, Any]], run_h: float, within_h: float = 24.0, load_kw: float = 1.0) -> dict[str, Any] | None:
    """The cheapest start (on the hour, or now) to run something for run_h hours drawing about load_kw, starting within
    within_h hours - and what it costs per kWh against starting now. Only the share its own spare sun covers counts at
    the feed-in price; the rest at the price. Only unbroken runs of hours (a gap in the prices is never bridged)."""
    from math import ceil

    if not hours:
        return None
    now = dt_util.utcnow()
    utc = [dt_util.as_utc(h["_t"]) for h in hours]
    n = max(1, ceil(run_h - 1e-9))
    weights = [1.0] * (n - 1) + [run_h - (n - 1)]  # the last hour only as far as it runs

    def eff(h: dict[str, Any]) -> float:
        spare = max(0.0, float(h.get("sun") or 0) - float(h.get("house") or 0))
        share = min(1.0, spare / max(load_kw, 0.1))
        return share * float(h.get("sell") or 0) + (1 - share) * float(h["price"])

    found = []
    for i in range(len(hours) - n + 1):
        if any((utc[i + k] - utc[i]).total_seconds() != k * 3600 for k in range(n)):
            continue  # a gap in the prices inside the run
        start = max(utc[i], now) if i == 0 else utc[i]
        if (start - now).total_seconds() > within_h * 3600:
            break
        avg = sum(eff(hours[i + k]) * weights[k] for k in range(n)) / run_h
        found.append((avg, i, start))
    if not found:
        return None
    avg, i, start = min(found, key=lambda x: (round(x[0], 4), x[1]))
    first = found[0]
    end = start + timedelta(hours=run_h)  # in UTC: right across the clocks changing
    loc = lambda t: dt_util.as_local(t).strftime("%a %H:%M")  # noqa: E731
    return {"start": loc(start), "end": loc(end), "starts_in_hours": round((start - now).total_seconds() / 3600, 1),
            "avg_price": round(avg, 3), "avg_price_if_started_now": round(first[0], 3) if first[1] == 0 else None,
            "saving_per_kwh": round(first[0] - avg, 3) if first[1] == 0 else None,
            "uses_own_sun": any(eff(hours[i + k]) < float(hours[i + k]["price"]) - 1e-6 for k in range(n))}


class _Tool(llm.Tool):
    integration = "energy_pilot"

    async def async_call(self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext) -> dict[str, Any]:
        pilot = _pilot(hass)
        if pilot is None or not pilot.data or not pilot.last_update_success:
            return {"error": "Energy Pilot isn't answering right now"}  # never an old state told as now
        try:
            return self.answer(pilot.data, tool_input.tool_args or {})
        except Exception as err:  # noqa: BLE001 - a tool never breaks the conversation
            _LOGGER.debug("Energy Pilot tool %s failed", self.name, exc_info=True)
            return {"error": str(err)[:200]}

    def answer(self, data: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError


class Now(_Tool):
    name = "energy_pilot_now"
    description = ("What Energy Pilot does right now and why: the battery's level and what it does, solar, the house's use, "
                   "buying or selling, the price now, and when the battery will be empty or full. Use for 'what is the "
                   "battery doing', 'why isn't it charging', 'how much sun', 'what does power cost now'.")

    def answer(self, data: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
        f, d, rt = data.get("flow") or {}, data.get("decision") or {}, data.get("runtime") or {}
        hours = _hours(data)
        return {"doing": d.get("text"), "why": d.get("reason"), "kind": d.get("kind"), "battery_target_pct": d.get("target"),
                "battery_pct": f.get("soc"), "watts": {"sun": f.get("pv"), "house": f.get("house"), "battery": f.get("battery"),
                                                       "grid_buy_plus_sell_minus": f.get("grid"), "car": f.get("ev")},
                "price_now": hours[0]["price"] if hours else None, "currency": data.get("currency"),
                "battery_lasts_until": _hm(rt.get("until")), "battery_full_at": _hm(rt.get("full")),
                "solar_kwh_today": (data.get("solar") or {}).get("solar_today"), "solar_kwh_tomorrow": (data.get("solar") or {}).get("solar_tomorrow"),
                "house_kwh_today": data.get("house_today"), "in_control": data.get("in_control")}


class Plan(_Tool):
    name = "energy_pilot_plan"
    description = ("Energy Pilot's plan hour by hour from now (up to 36 h): price, expected sun and house use, what the "
                   "battery does and its level after, when the car charges. Use for 'when is power cheapest', 'when will "
                   "the battery charge', 'what is the plan tonight'.")
    parameters = vol.Schema({vol.Optional("hours", description="How many hours ahead (default 24)"): vol.Coerce(int)})

    def answer(self, data: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
        n = max(1, min(36, int(args.get("hours") or 24)))
        rows = [{"at": h["_t"].strftime("%a %H:%M"), "price": h["price"], "sun_kwh": h.get("sun"), "house_kwh": h.get("house"),
                 "battery": h.get("action"), "battery_pct_after": h.get("soc"), "car_charges": bool(h.get("car"))} for h in _hours(data)[:n]]
        plan = data.get("plan") or {}
        return {"currency": data.get("currency"), "hours": rows, "cheapest_hours": [_hm(t) for t in plan.get("cheapest") or []],
                "price_min": plan.get("price_min"), "price_max": plan.get("price_max")}


class BestStart(_Tool):
    name = "energy_pilot_best_start"
    description = ("When it is cheapest to start an appliance or anything that runs for a while (dishwasher, washing "
                   "machine, dryer, car), with its own sun counted - and how much cheaper than starting now. Use for 'when "
                   "should I start the dishwasher', 'can it pay to wait'.")
    parameters = vol.Schema({
        vol.Optional("appliance", description="dishwasher, washing_machine, dryer, car or other"): str,
        vol.Optional("run_hours", description="How long it runs, if known"): vol.Coerce(float),
        vol.Optional("within_hours", description="Must start within this many hours (default 24)"): vol.Coerce(float),
    })

    def answer(self, data: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
        kind = str(args.get("appliance") or "other")
        run = float(args.get("run_hours") or RUNS.get(kind, RUNS["other"]))
        got = best_start(_hours(data), run, float(args.get("within_hours") or 24), LOAD_KW.get(kind, LOAD_KW["other"]))
        return {"currency": data.get("currency"), "run_hours": run, **(got or {"error": "no prices that far ahead yet"})}


class Car(_Tool):
    name = "energy_pilot_car"
    description = "The electric car: plugged in or not, its level, target, ready time, when it will charge and this charge so far."

    def answer(self, data: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
        ev = data.get("ev") or {}
        car_hours = [h["_t"].strftime("%a %H:%M") for h in _hours(data) if h.get("car")]
        return {"plugged_in": (data.get("flow") or {}).get("plug"), "level_pct": ev.get("soc"), "target_pct": ev.get("target"),
                "ready_at": ev.get("ready"), "charges_at": car_hours[:8], "this_charge": ev.get("charge"),
                "charging_watts": (data.get("flow") or {}).get("ev"), "more_cars": [{"name": c.get("name"), "plugged_in": c.get("plug"),
                                                                                    "level_pct": c.get("soc")} for c in data.get("cars") or []]}


class Savings(_Tool):
    name = "energy_pilot_savings"
    description = "What Energy Pilot saved: today, this month, this year and in all - month and total as a range (lo-hi), since some of it is an estimate."

    def answer(self, data: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
        lg = data.get("ledger") or {}
        keep = ("today", "month", "month_lo", "month_hi", "month_days", "year", "total", "total_lo", "total_hi", "since", "stored_kwh", "battery_kwh", "sun_share")
        return {"currency": data.get("currency"), **{k: lg.get(k) for k in keep if k in lg}}


class PilotAPI(llm.API):
    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(hass=hass, id=API_ID, name="Energy Pilot")

    async def async_get_api_instance(self, llm_context: llm.LLMContext) -> llm.APIInstance:
        return llm.APIInstance(api=self, api_prompt=PROMPT, llm_context=llm_context,
                               tools=[Now(), Plan(), BestStart(), Car(), Savings()])


def register(hass: HomeAssistant) -> Any:
    """Offer the tools to the AIs (once, also with several entries). Returns the undo, or None."""
    try:
        return llm.async_register_api(hass, PilotAPI(hass))
    except Exception:  # noqa: BLE001 - already there, or an older Home Assistant
        _LOGGER.debug("Energy Pilot tools not registered", exc_info=True)
        return None

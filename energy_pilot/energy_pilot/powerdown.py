"""Octopus Power Down (Saving) Sessions, UK: found by itself through the Octopus Energy integration, joined by itself
(joining costs nothing - only using less pays), and planned for: in a session's slots every kWh not bought (or sent
out) earns the reward on top, so the battery keeps power for it. 800 Octopoints are £1."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)
POINTS_PER_POUND = 800
KINDS = (("_octoplus_power_down_events", "join_octoplus_power_down_session_event"),
         ("_octoplus_saving_session_events", "join_octoplus_saving_session_event"))


def entities(states: dict[str, Any]) -> list[tuple[str, str]]:
    """(events entity, join service) - the new Power Down one first; the old one only when there is no new."""
    for suffix, service in KINDS:
        found = [(e, service) for e in states if e.startswith("event.octopus_energy_") and e.endswith(suffix)]
        if found:
            return found
    return []


def _t(v: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(v))
    except (TypeError, ValueError):
        return None


def sessions(states: dict[str, Any]) -> list[dict[str, Any]]:
    """The joined sessions still to come or running: start, end and the reward per kWh in pounds."""
    out = []
    for e, _ in entities(states):
        for ev in ((states.get(e) or {}).get("attributes") or {}).get("joined_events") or []:
            s, t = _t(ev.get("start")), _t(ev.get("end"))
            if s and t:
                out.append({"start": s, "end": t, "value": float(ev.get("octopoints_per_kwh") or 0) / POINTS_PER_POUND})
    return out


def apply(hours: list[Any], now: datetime, states: dict[str, Any]) -> list[dict[str, Any]]:
    """Adds a session's reward to the slots it covers. Returns the sessions in the plan."""
    used = []
    for ss in sessions(states):
        if ss["end"] <= now or ss["value"] <= 0:
            continue
        hit = False
        for h in hours:
            if ss["start"] <= h.start < ss["end"]:
                h.price += ss["value"]
                h.sell += ss["value"]
                hit = True
        if hit:
            used.append(ss)
    return used


async def join(ha: Any, states: dict[str, Any], now: datetime, done: set[str]) -> list[str]:
    """Joins every session on offer that hasn't started. Returns the codes joined now."""
    joined = []
    for e, service in entities(states):
        for ev in ((states.get(e) or {}).get("attributes") or {}).get("available_events") or []:
            code, start = str(ev.get("code") or ""), _t(ev.get("start"))
            if not code or code in done or not start or start <= now:
                continue
            done.add(code)
            try:
                await ha.call_service("octopus_energy", service, {"entity_id": e, "event_code": code})
                joined.append(code)
                _LOGGER.info("Joined the Octopus session %s at %s", code, start)
            except Exception:  # noqa: BLE001 - tried once; it may have gone
                _LOGGER.info("Could not join the Octopus session %s", code, exc_info=True)
    return joined


# Octopus Power Up (once "Free Electricity"): power is free in a session's slots, though the price sensor doesn't show
# it - found by itself the same way, and planned with the price at nothing, so the battery and the car fill up then.
FREE = ("_octoplus_power_up_events", "_octoplus_free_electricity_session_events")


def free_sessions(states: dict[str, Any], tz: Any = None) -> list[dict[str, Any]]:
    """The free sessions (start, end): the new Power Up entity first; the old one only when there is no new."""
    for suffix in FREE:
        ents = [e for e in states if e.startswith("event.octopus_energy_") and e.endswith(suffix)]
        if not ents:
            continue
        out = []
        for e in ents:
            for ev in ((states.get(e) or {}).get("attributes") or {}).get("events") or []:
                s, t = _t((ev or {}).get("start")), _t((ev or {}).get("end"))
                if s and t:
                    if s.tzinfo is None and tz is not None:
                        s, t = s.replace(tzinfo=tz), t.replace(tzinfo=tz)
                    out.append({"start": s, "end": t})
        return out
    return []


def apply_free(hours: list[Any], now: datetime, states: dict[str, Any]) -> list[dict[str, Any]]:
    """The part of each slot inside a free session costs nothing. Returns the sessions in the plan."""
    used = []
    for ss in free_sessions(states, now.tzinfo):
        try:
            if ss["end"] <= now:
                continue
        except TypeError:
            continue  # a time without a zone against one with
        hit = False
        for h in hours:
            end = h.start + timedelta(hours=h.length)
            inside = (min(end, ss["end"]) - max(h.start, ss["start"])).total_seconds() / 3600
            if inside > 0:
                h.price *= max(0.0, 1 - inside / h.length)
                hit = True
        if hit:
            used.append(ss)
    return used

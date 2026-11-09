"""How fast the car charges right now: with the sun's surplus, at full speed in the planned hours, never over the fuse.

- Follow the sun (setting, on by default with solar): the current follows what the sun has left over after the house
  and the house battery's charging, from 6 A up to the charger's setting. With a clear surplus the car also charges
  outside the planned hours, so little is sold cheaply. A small margin keeps it from switching on and off.
- Planned hours without much sun (cheap night hours, or charging now): full speed.
- Mind the main fuse (setting, on when an import limit is set): house + battery + car may not buy more than the
  limit; the car is turned down first, and stopped if even 6 A would be too much.
"""

from __future__ import annotations

from typing import Any

VOLT = 230
MIN_A = 6
MARGIN_W = 300  # start a little above, stop a little below the 6 A power - no switching on and off


def decide(flow: dict[str, Any], s: dict[str, Any], planned: bool, manual: bool, need_kwh: float,
           sun_was_on: bool) -> dict[str, Any]:
    """{"charge": bool, "current": A, "sun": bool, "why": str}."""
    kw = float(s.get("charger_kw") or 7.4)
    phases = int(s.get("charger_phases") or (3 if kw > 7.5 else 1))
    max_a = min(32, max(MIN_A, round(kw * 1000 / (VOLT * phases))))
    per_a = VOLT * phases
    min_w = MIN_A * per_a
    plug = bool(flow.get("plug"))
    if not plug or (need_kwh <= 0 and not manual):
        return {"charge": False, "current": max_a, "sun": False, "why": "no_need" if plug else "not_plugged"}
    pv, house = flow.get("pv"), flow.get("house")
    batt_in = max(0.0, flow.get("battery") or 0.0)  # the house battery charging takes the sun first
    follow = s.get("ev_follow_sun", True) and pv is not None and house is not None
    surplus = (pv - house - batt_in) if follow else 0.0
    sun = follow and surplus >= (min_w - MARGIN_W if sun_was_on else min_w + MARGIN_W)
    if manual:
        charge, amps, why = True, max_a, "manual"
    elif sun:
        charge, amps, why = True, max(MIN_A, min(max_a, int(surplus // per_a))), "sun"
    elif planned:
        charge, amps, why = True, max_a, "planned"
    else:
        return {"charge": False, "current": max_a, "sun": False, "why": "waiting"}
    # The main fuse: what the house and battery buy, plus the car, stays under the limit.
    limit = s.get("import_limit_kw")
    if charge and limit and s.get("ev_fuse_guard", True) and house is not None:
        car_now = max(0.0, flow.get("ev") or 0.0)
        grid = flow.get("grid")
        others = (grid - car_now) if grid is not None else (house + batt_in - (pv or 0.0))
        room = float(limit) * 1000 - others
        fit = int(room // per_a)
        if fit < MIN_A:
            return {"charge": False, "current": max_a, "sun": False, "why": "fuse"}
        if fit < amps:
            amps, why = fit, why + "+fuse"
    # Power tariff: keep under the month's peak so far by turning down - but never stopping for it.
    peak = s.get("peak_kw")
    if charge and peak and not manual and house is not None:
        car_now = max(0.0, flow.get("ev") or 0.0)
        grid = flow.get("grid")
        others = (grid - car_now) if grid is not None else (house + batt_in - (pv or 0.0))
        fit = int((float(peak) * 1000 - others) // per_a)
        if fit < amps:
            amps, why = max(MIN_A, fit), why + "+peak"
    return {"charge": charge, "current": amps, "sun": sun, "why": why}

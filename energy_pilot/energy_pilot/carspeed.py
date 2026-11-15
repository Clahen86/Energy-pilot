"""How fast the car charges right now: with the sun's surplus, at full speed in the planned hours, never over the fuse.

- Follow the sun (setting, on by default with solar): the current follows what the sun has left over after the house
  and the house battery's charging, from 6 A up to the charger's setting. With a clear surplus the car also charges
  outside the planned hours, so little is sold cheaply. A small margin keeps it from switching on and off.
- Planned hours without much sun (cheap night hours, or charging now): full speed. PV-only mode charges only
  from surplus, never from grid.
- Mind the main fuse (setting, on when an import limit is set): house + battery + car may not buy more than the
  limit; the car is turned down first, and stopped if even 6 A would be too much.
"""

from __future__ import annotations

from typing import Any

VOLT = 230
MIN_A = 6
MIN_A_1PH = 6
MARGIN_W = 300  # start a little above, stop a little below the 6 A power - no switching on and off
MIN_SURPLUS_3PH_W = 4200  # ~6 A * 3 * 230 V
MIN_SURPLUS_1PH_W = 1400  # ~6 A * 1 * 230 V


def decide(flow: dict[str, Any], s: dict[str, Any], planned: bool, manual: bool, need_kwh: float,
           sun_was_on: bool) -> dict[str, Any]:
    """{"charge": bool, "current": A, "sun": bool, "why": str, "phases": 1|3}."""
    kw = float(s.get("charger_kw") or 7.4)
    configured_phases = int(s.get("charger_phases") or (3 if kw > 7.5 else 1))
    max_a = min(32, max(MIN_A, round(kw * 1000 / (VOLT * configured_phases))))
    per_a_3ph = VOLT * 3
    per_a_1ph = VOLT * 1
    # A plain on/off switch (a Shelly, a smart plug): full power or nothing. A charger with fixed steps (8/10/13 A):
    # its lowest step - below it, it would still take that step and go over the fuse.
    lo_3ph = max_a if s.get("onoff") else min(max_a, max(MIN_A, int(s.get("min_a") or MIN_A)))
    lo_1ph = max(MIN_A_1PH, min(max_a, max(MIN_A_1PH, int(s.get("min_a") or MIN_A_1PH)))) if not s.get("onoff") else max_a
    min_w_3ph = lo_3ph * per_a_3ph
    min_w_1ph = lo_1ph * per_a_1ph
    plug = bool(flow.get("plug"))
    if not plug or (need_kwh <= 0 and not manual):
        return {"charge": False, "current": max_a, "sun": False, "why": "no_need" if plug else "not_plugged", "phases": configured_phases}
    pv, house = flow.get("pv"), flow.get("house")
    batt_in = max(0.0, flow.get("battery") or 0.0)  # the house battery charging takes the sun first
    follow = s.get("ev_follow_sun", True) and pv is not None and house is not None
    pv_only = s.get("ev_mode") == "solar" or s.get("ev_pv_only", False)
    surplus = (pv - house - batt_in) if follow else 0.0
    # Phase selection: prefer 1-phase for low surplus, 3-phase for high surplus
    use_1ph = False
    if follow and surplus > 0:
        if surplus >= MIN_SURPLUS_3PH_W:
            phases = 3
            per_a = per_a_3ph
            lo = lo_3ph
            min_w = min_w_3ph
        elif surplus >= MIN_SURPLUS_1PH_W:
            phases = 1
            use_1ph = True
            per_a = per_a_1ph
            lo = lo_1ph
            min_w = min_w_1ph
        else:
            phases = configured_phases
            per_a = VOLT * phases
            lo = lo_3ph if phases == 3 else lo_1ph
            min_w = lo * per_a
    else:
        phases = configured_phases
        per_a = VOLT * phases
        lo = lo_3ph if phases == 3 else lo_1ph
        min_w = lo * per_a
    sun = follow and surplus >= (min_w - MARGIN_W if sun_was_on else min_w + MARGIN_W)
    if pv_only and not sun:
        # In PV-only mode, only charge when there's enough surplus
        return {"charge": False, "current": max_a, "sun": False, "why": "pv_only_waiting", "phases": phases}
    if manual:
        charge, amps, why = True, max_a, "manual"
    elif sun:
        # Clamp to configured phases max
        max_a_for_phases = min(32, max(MIN_A, round(kw * 1000 / (VOLT * phases))))
        charge, amps, why = True, max(lo, min(max_a_for_phases, int(surplus // per_a))), "sun"
    elif planned:
        charge, amps, why = True, max_a, "planned"
    else:
        return {"charge": False, "current": max_a, "sun": False, "why": "waiting", "phases": phases}
    # The main fuse: what the house and battery buy, plus the car, stays under the limit.
    limit = s.get("import_limit_kw")
    if charge and limit and s.get("ev_fuse_guard", True) and house is not None:
        car_now = max(0.0, flow.get("ev") or 0.0)
        grid = flow.get("grid")
        others = (grid - car_now) if grid is not None else (house + batt_in - (pv or 0.0))
        room = float(limit) * 1000 - others
        fit = int(room // per_a)
        if fit < lo:
            return {"charge": False, "current": max_a, "sun": False, "why": "fuse", "phases": phases}
        if fit < amps:
            amps, why = fit, why + "+fuse"
    # Power tariff: keep under the month's peak so far by turning down - but never stopping for it.
    peak = s.get("peak_kw")
    if charge and peak and not manual and house is not None:
        car_now = max(0.0, flow.get("ev") or 0.0)
        grid = flow.get("grid")
        others = (grid - car_now) if grid is not None else (house + batt_in - (pv or 0.0))
        fit = int((float(peak) * 1000 - others) // per_a)
        if fit < amps and lo < max_a:
            amps, why = max(lo, fit), why + "+peak"
    return {"charge": charge, "current": amps, "sun": sun, "why": why, "phases": phases, "use_1ph": use_1ph}
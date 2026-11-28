"""How fast the car charges right now: with the sun's surplus, at full speed in the planned hours, never over the fuse.

- Follow the sun (setting, on by default with solar): the current follows what the sun has left over after the house
  and the house battery's charging, from 6 A up to the charger's setting. With a clear surplus the car also charges
  outside the planned hours, so little is sold cheaply. A small margin keeps it from switching on and off.
- Planned hours without much sun (cheap night hours, or charging now): full speed. In "Sun" mode the planned
  (sunny) hours charge only on the surplus actually there - a cloud never makes it buy from the grid. "Charge now"
  still charges at full speed.
- 1 or 3 phases (setting, only for a charger with its own phase choice): on a small surplus it charges on 1 phase
  (from about 1.4 kW instead of 4.1), on 3 when the surplus is big - with a margin, and at most every 10 minutes.
- The house battery may not charge from the grid (and isn't full): it gets the sun first, the car what is left -
  turned down, never stopped in its planned hours. A charger that can't be turned down (on/off) isn't touched.
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
    max_a = min(32, max(MIN_A, round(kw * 1000 / (VOLT * phases))))  # per phase - the same on 1 phase
    # A plain on/off switch (a Shelly, a smart plug): full power or nothing. A charger with fixed steps (8/10/13 A):
    # its lowest step - below it, it would still take that step and go over the fuse.
    lo = max_a if s.get("onoff") else min(max_a, max(MIN_A, int(s.get("min_a") or MIN_A)))
    plug = bool(flow.get("plug"))
    if not plug or (need_kwh <= 0 and not manual):
        return {"charge": False, "current": max_a, "sun": False, "why": "no_need" if plug else "not_plugged", "phases": None}
    pv, house = flow.get("pv"), flow.get("house")
    # The house battery charging takes the sun first - unless the style is "Car first": then what goes into the battery
    # is the car's to take (the inverter gives the battery less as the car starts), so a battery soaking up the whole
    # surplus no longer keeps the car waiting until it's full.
    car_first = s.get("style") == "car_first"
    batt_in = 0.0 if car_first else max(0.0, flow.get("battery") or 0.0)
    follow = s.get("ev_follow_sun", True) and pv is not None and house is not None
    surplus = (pv - house - batt_in) if follow else 0.0
    sun_first = s.get("batt_sun_w") and pv is not None and house is not None and not car_first
    if follow and sun_first:
        # The house battery may not charge from the grid: the sun fills it first, the car gets what is left.
        surplus = pv - house - max(batt_in, float(s["batt_sun_w"]))
    # 1 or 3 phases: only a 3-phase charger with its own phase choice (s["phase_switch"]); held while locked.
    switch = bool(s.get("phase_switch")) and phases == 3 and not s.get("onoff")
    now_ph = int(s.get("phase_now") or 3)
    if switch and follow and not manual:
        if s.get("phase_lock"):
            phases = now_ph
        else:
            big = lo * VOLT * 3 + (-MARGIN_W if now_ph == 3 and sun_was_on else MARGIN_W)
            phases = 3 if surplus >= big else 1
    elif switch:
        phases = now_ph if s.get("phase_lock") else 3
    per_a = VOLT * phases
    min_w = lo * per_a
    sun = follow and surplus >= (min_w - MARGIN_W if sun_was_on else min_w + MARGIN_W)
    sun_only = s.get("ev_mode") == "solar"
    if manual:
        charge, amps, why = True, max_a, "manual"
    elif sun:
        charge, amps, why = True, max(lo, min(max_a, int(surplus // per_a))), "sun"
    elif planned and not sun_only:
        charge, amps, why = True, max_a, "planned"
        if sun_first and pv > house:
            # ... also in the planned hours while the sun shines: turned down (never stopped - it still gets ready)
            fit = max(lo, int(max(0.0, pv - house - float(s["batt_sun_w"])) // per_a))
            if fit < amps:
                amps, why = fit, "planned+battery"
    else:
        return {"charge": False, "current": max_a, "sun": False, "why": "sun_only" if planned else "waiting", "phases": None}
    if switch and (manual or (planned and not sun)) and not s.get("phase_lock"):
        phases, per_a = 3, VOLT * 3  # full speed: all 3 phases
    # The main fuse: what the house and battery buy, plus the car, stays under the limit.
    limit = s.get("import_limit_kw")
    if charge and limit and s.get("ev_fuse_guard", True) and house is not None:
        car_now = max(0.0, flow.get("ev") or 0.0)
        grid = flow.get("grid")
        others = (grid - car_now) if grid is not None else (house + batt_in - (pv or 0.0))
        room = float(limit) * 1000 - others
        fit = int(room // per_a)
        if fit < lo:
            return {"charge": False, "current": max_a, "sun": False, "why": "fuse", "phases": None}
        if fit < amps:
            amps, why = fit, why + "+fuse"
    # The main fuse per phase (phases.py): amps left on the busiest phase. The car's own current is in the meter's
    # reading already, so it comes back on top; on one phase it may be the busiest one, on three it is on all.
    if charge and s.get("phase_room_a") is not None:
        car_now_a = max(0.0, flow.get("ev") or 0.0) / per_a
        fit = int(float(s["phase_room_a"]) + car_now_a)
        if fit < lo:
            return {"charge": False, "current": max_a, "sun": False, "why": "fuse", "phases": None}
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
    return {"charge": charge, "current": amps, "sun": sun, "why": why, "phases": phases if switch else None}

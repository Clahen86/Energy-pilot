"""How long the battery lasts - worked out hour by hour, not from the power right now (that jumps every time the
kettle is on). Two answers:

- "until": how long the battery carries the house without power from the grid - the house's expected use (what the
  engine has learned) minus the sun's forecast, from the level now down to the lowest level. The number people want,
  also when the grid goes down.
- the plan's curve: the battery hour by hour as planned - where it is lowest tonight, when it charges cheaply, when
  it is full.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def _f(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def compute(plan: dict[str, Any], flow: dict[str, Any], capacity_kwh: float, min_soc: float, now: datetime,
            storm: dict[str, Any] | None = None) -> dict[str, Any] | None:
    soc = _f((flow or {}).get("soc"))
    rows = [(datetime.fromisoformat(h["t"]), h) for h in (plan or {}).get("hours") or [] if h.get("t")]
    rows = [(t, h) for t, h in rows if t + timedelta(hours=1) > now]
    if soc is None or not capacity_kwh or not rows:
        return None
    house_now_kw = (_f((flow or {}).get("house")) or 0.0) / 1000
    room = max(0.0, (soc - min_soc) / 100 * capacity_kwh)  # what can still come out
    top = max(0.0, (100 - min_soc) / 100 * capacity_kwh)
    until, used, hours_used = None, 0.0, 0.0
    for i, (t, h) in enumerate(rows):
        frac = 1.0 if i else max(0.05, 1 - (now - t).total_seconds() / 3600)  # what is left of this hour
        start = now if i == 0 else t
        house = _f(h.get("house"))
        house = house if house is not None else house_now_kw
        net = (house - (_f(h.get("sun")) or 0.0)) * frac  # kWh the battery must give (minus: the sun fills it)
        if net > 0 and room - net <= 0:
            until = start + timedelta(hours=frac * room / net)
            used += room
            break
        room = min(top, room - net)
        if net > 0:
            used += net
        hours_used += frac
    curve = [{"t": t.isoformat(), "soc": round(_f(h.get("soc")) or 0, 1), "charge": bool(h.get("charge")), "sun": round(_f(h.get("sun")) or 0, 2)}
             for t, h in rows if t < now + timedelta(hours=24) and h.get("soc") is not None]
    night = [c for c in curve if datetime.fromisoformat(c["t"]) < now + timedelta(hours=18)]
    low = min(night, key=lambda c: c["soc"]) if night else None
    full = next((c for c in curve if c["soc"] >= 95), None)
    cheap = None
    for i, c in enumerate(curve):
        if c["charge"]:
            j = i
            while j + 1 < len(curve) and curve[j + 1]["charge"]:
                j += 1
            cheap = {"from": c["t"], "to": (datetime.fromisoformat(curve[j]["t"]) + timedelta(hours=1)).isoformat()}
            break
    end = rows[-1][0] + timedelta(hours=1)
    span_h = ((until or end) - now).total_seconds() / 3600
    return {
        "soc": round(soc, 1), "kwh": round(soc / 100 * capacity_kwh, 1), "min_soc": min_soc, "empty": soc <= min_soc + 0.5,
        "until": until.isoformat() if until else None, "beyond": None if until else end.isoformat(),
        "hours": round(span_h, 2), "house_kw": round(used / hours_used, 2) if hours_used and used else round(house_now_kw, 2),
        "low": low, "full": full["t"] if full else None, "cheap": cheap, "curve": curve, "storm": storm,
    }

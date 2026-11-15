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


ACTION = {"charge_grid": "charge", "charge_sun": "sun", "discharge": "use", "hold": "hold", "export": "sell"}


def next_action(steps: list[dict[str, Any]] | None, now: datetime) -> dict[str, Any] | None:
    """What the battery does now and until when - and what comes after. From the plan's steps."""
    rows = []
    for x in steps or []:
        try:
            rows.append((datetime.fromisoformat(x["t"]), ACTION.get(x.get("action"), "hold"), x.get("soc")))
        except (KeyError, TypeError, ValueError):
            continue
    rows.sort(key=lambda r: r[0])
    # the plan's slots may be quarters: each step lasts until the next one starts
    slot = min((b[0] - a[0] for a, b in zip(rows, rows[1:]) if b[0] > a[0]), default=timedelta(hours=1))
    rows = [r for r in rows if r[0] + slot > now]
    if not rows:
        return None
    do, i = rows[0][1], 0
    while i + 1 < len(rows) and rows[i + 1][1] == do:
        i += 1
    out = {"do": do, "to": (rows[i][0] + slot).isoformat(), "soc": rows[i][2]}
    if i + 1 < len(rows):
        out["then"] = rows[i + 1][1]
    return out


def evening(curve: list[dict[str, Any]], soc: float, cap: float, min_soc: float, hours: int = 4) -> dict[str, Any] | None:
    """The dearest few hours ahead: does the battery hold enough for them?"""
    if len(curve) < hours + 1 or any(c.get("price") is None for c in curve):
        return None
    best, at = None, None
    for i in range(1, len(curve) - hours + 1):
        avg = sum(c["price"] for c in curve[i:i + hours]) / hours
        if best is None or avg > best:
            best, at = avg, i
    win = curve[at:at + hours]
    need = sum(max(0.0, (c.get("house") or 0.0) - (c.get("sun") or 0.0)) for c in win)
    if need < 0.3:
        return None
    start = curve[at - 1]["soc"] if at else soc
    have = max(0.0, (start - min_soc) / 100 * cap)
    return {"from": win[0]["t"], "to": (datetime.fromisoformat(win[-1]["t"]) + timedelta(hours=1)).isoformat(),
            "need": round(need, 1), "have": round(have, 1), "ok": have >= need * 0.95}


def compute(plan: dict[str, Any], flow: dict[str, Any], capacity_kwh: float, min_soc: float, now: datetime,
            storm: dict[str, Any] | None = None, steps: list[dict[str, Any]] | None = None,
            events: list[dict[str, Any]] | None = None, sky: dict[str, Any] | None = None) -> dict[str, Any] | None:
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
    curve = [{"t": t.isoformat(), "soc": round(_f(h.get("soc")) or 0, 1), "charge": bool(h.get("charge")), "sun": round(_f(h.get("sun")) or 0, 2),
              "house": round(_f(h.get("house")) or house_now_kw, 2), "price": _f(h.get("price"))}
             for t, h in rows if t < now + timedelta(hours=24) and h.get("soc") is not None]
    prices = sorted(c["price"] for c in curve if c["price"] is not None)
    if len(prices) >= 6:  # the dear hours: the top quarter - when prices differ at all
        thr = prices[int(len(prices) * 0.75)]
        for c in curve:
            c["dear"] = c["price"] is not None and c["price"] >= thr and c["price"] > prices[0] * 1.15
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
        "cap": capacity_kwh, "next": next_action(steps, now), "evening": evening(curve, soc, capacity_kwh, min_soc),
        "base": _base(curve, soc, capacity_kwh, min_soc),
        "events": [e for e in events or [] if curve and curve[0]["t"] <= e["t"] <= curve[-1]["t"]], "sky": sky,
    }


def _base(curve: list[dict[str, Any]], soc: float, cap: float, min_soc: float) -> dict[str, Any] | None:
    """With only the house's least use (fridge, lights, internet): how long the battery lasts."""
    use = sorted(c["house"] for c in curve if c.get("house"))
    if len(use) < 6:
        return None
    kw = max(0.1, sum(use[:3]) / 3)
    room = max(0.0, (soc - min_soc) / 100 * cap)
    return {"kw": round(kw, 2), "h": round(min(99.0, room / kw), 1)}

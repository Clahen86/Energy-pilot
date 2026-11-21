"""The panels' own shape: which way they face, where shade falls, and how the forecast should be bent hour by hour.

A solar forecast only knows what the user typed in (or nothing). On clear days the production itself tells the rest:
panels facing east give most in the morning, west in the afternoon, a tree shows as a dip at the same hour every clear
day. Two things are learned, both only from clear days (little cloud, so what is seen is the panels, not the weather):

- per hour of the day: how the real production is spread over the day against the forecast's spread. The level stays
  with the sun bias in learning.py; this only moves the forecast between the hours. Used by the plan.
- the direction: the clear days' production is matched with clear-sky curves for panels facing every way. Shown in
  the settings only - nothing is changed by it. The forecast's own clear days are matched the same way, so a forecast
  set up for the wrong direction can be pointed out.

Hours where the production sits flat at its top (the inverter's limit, or a full battery with export blocked) are left
out: they say nothing about the panels.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from statistics import median
from typing import Any

MIN_SEEN = 3  # an hour's factor is used once it was seen on this many clear hours
KEEP_DAYS = 40  # clear days kept for the direction
SURE_DAYS = 5  # clear days before the direction is shown as found
CLEAR_CLOUD = 30  # mean cloud cover (%) for a clear day
SHADE = 0.72  # an hour giving less than this of the fitted clear-sky curve on most clear days is shaded
MISMATCH_DEG = 45


# ---------- the sun's position and clear-sky curves ----------

def sun_pos(t: datetime, lat: float, lon: float) -> tuple[float, float]:
    """(elevation, azimuth from north) in degrees at time t (aware) - NOAA's short formulas."""
    u = t.astimezone(timezone.utc)
    doy = u.timetuple().tm_yday
    hr = u.hour + u.minute / 60
    g = 2 * math.pi / 365 * (doy - 1 + (hr - 12) / 24)
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g) - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
            - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    ha = math.radians((hr * 60 + eqt + 4 * lon) / 4 - 180)
    phi = math.radians(lat)
    cz = max(-1.0, min(1.0, math.sin(phi) * math.sin(decl) + math.cos(phi) * math.cos(decl) * math.cos(ha)))
    zen = math.acos(cz)
    az = (math.degrees(math.atan2(math.sin(ha), math.cos(ha) * math.sin(phi) - math.tan(decl) * math.cos(phi))) + 180) % 360
    return 90 - math.degrees(zen), az


def _sky(elev: float) -> float:
    """Direct sunlight (W/m2) through a clear sky at this elevation."""
    if elev <= 1:
        return 0.0
    zen = 90 - elev
    am = 1 / (math.cos(math.radians(zen)) + 0.50572 * (96.07995 - zen) ** -1.6364)
    return 1361 * 0.7 ** (am ** 0.678)


def _poa(elev: float, saz: float, dni: float, az: float, tilt: float) -> float:
    if dni <= 0:
        return 0.0
    zen, t = math.radians(90 - elev), math.radians(tilt)
    cos_i = math.cos(zen) * math.cos(t) + math.sin(zen) * math.sin(t) * math.cos(math.radians(saz - az))
    return dni * max(0.0, cos_i) + 0.1 * dni * (1 + math.cos(t)) / 2


CANDIDATES: list[tuple[float, float, bool]] = (
    [(float(az), float(tilt), False) for az in range(60, 301, 10) for tilt in (15, 35, 55)]
    + [(float(az), float(tilt), True) for az in range(60, 121, 10) for tilt in (10, 25)]  # east + west, half each
)


def _positions(day: str, hours: list[int], tz: Any, lat: float, lon: float) -> dict[int, list[tuple[float, float, float]]]:
    """Per hour: (elevation, azimuth, direct light) at three moments inside it."""
    base = datetime.fromisoformat(day).replace(tzinfo=tz)
    out = {}
    for h in hours:
        pts = []
        for m in (10, 30, 50):
            e, a = sun_pos(base + timedelta(hours=h, minutes=m), lat, lon)
            pts.append((e, a, _sky(e)))
        out[h] = pts
    return out


def _curve(pos: dict[int, list[tuple[float, float, float]]], cand: tuple[float, float, bool]) -> dict[int, float]:
    az, tilt, ew = cand
    out = {}
    for h, pts in pos.items():
        if ew:
            v = sum(0.5 * _poa(e, a, d, az, tilt) + 0.5 * _poa(e, a, d, (az + 180) % 360, tilt) for e, a, d in pts)
        else:
            v = sum(_poa(e, a, d, az, tilt) for e, a, d in pts)
        out[h] = v / 3
    return out


def _norm(d: dict[int, float]) -> dict[int, float]:
    s = sum(d.values())
    return {h: v / s for h, v in d.items()} if s > 0 else {}


def plateau(vals: dict[int, float]) -> set[int]:
    """Hours sitting flat at the day's top - clipped by the inverter or a full battery, not the panels' shape."""
    if not vals:
        return set()
    top = max(vals.values())
    near = {h for h, v in vals.items() if top > 0 and v >= 0.97 * top}
    return near if len(near) >= 3 else set()


# ---------- learning ----------

def clear_day(exp: dict[str, dict[str, Any]], pv: dict[str, float], day: str, tz: Any, lat: float, lon: float) -> dict[str, Any] | None:
    """The day's production by hour, if it was a clear day with production all through the daylight: {"d", "real", "fc"}."""
    hours = [h for h in range(24) if sun_pos(datetime.fromisoformat(day).replace(tzinfo=tz) + timedelta(hours=h, minutes=30), lat, lon)[0] > 5]
    if len(hours) < 6:
        return None
    clouds = [exp.get(f"{day}T{h:02d}", {}).get("cloud") for h in hours]
    known = [c for c in clouds if isinstance(c, (int, float))]
    if len(known) < 0.8 * len(hours) or sum(known) / len(known) > CLEAR_CLOUD or max(known) > 60:
        return None
    real = {h: float(pv[f"{day}T{h:02d}"]) for h in hours if isinstance(pv.get(f"{day}T{h:02d}"), (int, float))}
    if len(real) < len(hours) or sum(real.values()) < 0.5 or any(v < 0 for v in real.values()):
        return None
    fc = {h: float(exp[f"{day}T{h:02d}"]["sun_raw"]) for h in hours
          if isinstance(exp.get(f"{day}T{h:02d}", {}).get("sun_raw"), (int, float))}
    return {"d": day, "real": {str(h): round(v, 3) for h, v in real.items()},
            "fc": {str(h): round(v, 3) for h, v in fc.items()} if len(fc) == len(hours) else None}


def learn_hours(state: dict[str, Any], exp: dict[str, dict[str, Any]], pv: dict[str, float], day: str) -> int:
    """Move each clear hour's factor a fifth of the way towards what it gave against the forecast - the day's level taken
    out, so only the spread over the day is learned. Returns the hours learned from."""
    rows = []
    for h in range(24):
        e = exp.get(f"{day}T{h:02d}") or {}
        raw, real, cloud = e.get("sun_raw"), pv.get(f"{day}T{h:02d}"), e.get("cloud")
        if isinstance(raw, (int, float)) and isinstance(real, (int, float)) and isinstance(cloud, (int, float)) and cloud < 40 and raw >= 0.1:
            rows.append((h, float(raw), float(real)))
    if len(rows) < 3:
        return 0
    top = max(r for _, r, _ in rows)
    flat = plateau({h: real for h, _, real in rows})
    rows = [(h, raw, real) for h, raw, real in rows if raw >= 0.1 * top and h not in flat]
    if len(rows) < 3:
        return 0
    level = sum(real for _, _, real in rows) / sum(raw for _, raw, _ in rows)
    if level <= 0.05:
        return 0
    got = state.setdefault("sun_hour", {})
    for h, raw, real in rows:
        r = max(0.3, min(2.0, real / raw / level))
        f, n = got.get(str(h), [1.0, 0])
        got[str(h)] = [round(0.8 * f + 0.2 * r, 3), n + 1]
    _centre(got)
    return len(rows)


def _centre(got: dict[str, list]) -> None:
    """Keep the factors around 1 on average, so they bend the day without lifting or lowering it (that's the bias)."""
    used = [f for f, n in got.values() if n >= MIN_SEEN]
    if len(used) < 3:
        return
    m = sum(used) / len(used)
    if m > 0:
        for k, (f, n) in got.items():
            got[k] = [round(f / m, 3), n]


def factor(state: dict[str, Any], hour: int | None, cloud: float | None) -> float:
    """How much to bend this hour's forecast. Full on clear hours; under clouds the light is spread and shade or the
    panels' direction matter less, so only part of it."""
    if hour is None:
        return 1.0
    f, n = (state.get("sun_hour") or {}).get(str(hour), [1.0, 0])
    if n < MIN_SEEN:
        return 1.0
    f = max(0.5, min(1.5, float(f)))
    return f if (cloud or 0) < 60 else 1 + 0.4 * (f - 1)


def add_day(state: dict[str, Any], got: dict[str, Any] | None) -> None:
    if not got:
        return
    days = [d for d in (state.get("clear_days") or []) if d.get("d") != got["d"]]
    state["clear_days"] = (days + [got])[-KEEP_DAYS:]


# ---------- the direction ----------

def fit(days: list[dict[str, Any]], key: str, tz: Any, lat: float, lon: float, pos_cache: dict | None = None) -> dict[str, Any] | None:
    """The panels (az, tilt, east/west) whose clear-sky curve fits these days best, the hours that are shaded, and how
    good the fit is. key: "real" (the production) or "fc" (the forecast)."""
    use = [(d["d"], {int(h): v for h, v in d[key].items()}) for d in days if d.get(key)]
    if not use:
        return None
    pos_cache = {} if pos_cache is None else pos_cache
    pos = {}
    for day, vals in use:
        if day not in pos_cache:
            pos_cache[day] = _positions(day, sorted(vals), tz, lat, lon)
        pos[day] = pos_cache[day]
    skip: dict[str, set[int]] = {day: plateau(vals) for day, vals in use}

    def score(cand: tuple[float, float, bool], shade: set[int]) -> float:
        errs = []
        for day, vals in use:
            hrs = [h for h in vals if h not in skip[day] and h not in shade]
            r = _norm({h: vals[h] for h in hrs})
            m = _norm({h: v for h, v in _curve(pos[day], cand).items() if h in hrs})
            if r and m:
                errs.append(sum(abs(r[h] - m.get(h, 0.0)) for h in r))
        return median(errs) if errs else 9.0

    best = min(CANDIDATES, key=lambda c: score(c, set()))
    shade = shaded(use, pos, skip, best) if key == "real" else set()
    if shade:
        best = min(CANDIDATES, key=lambda c: score(c, shade))
        shade = shaded(use, pos, skip, best)
    return {"az": best[0], "tilt": best[1], "ew": best[2], "err": round(score(best, shade), 3), "shade": sorted(shade), "days": len(use)}


def shaded(use: list, pos: dict, skip: dict, cand: tuple[float, float, bool]) -> set[int]:
    """Hours giving clearly less than the clear-sky curve, on most clear days."""
    by_h: dict[int, list[float]] = {}
    for day, vals in use:
        hrs = [h for h in vals if h not in skip[day]]
        curve = _curve(pos[day], cand)
        r, m = _norm({h: vals[h] for h in hrs}), _norm({h: curve[h] for h in hrs if h in curve})
        top = max(m.values()) if m else 0
        for h in hrs:
            if m.get(h, 0) >= 0.25 * top and m.get(h, 0) > 0:
                by_h.setdefault(h, []).append(r.get(h, 0) / m[h])
    return {h for h, rs in by_h.items() if len(rs) >= 3 and median(rs) < SHADE}


def spans(hours: list[int]) -> list[list[int]]:
    """[13, 14, 15, 18] -> [[13, 16], [18, 19]]: from-to clock hours."""
    out: list[list[int]] = []
    for h in sorted(hours):
        if out and out[-1][1] == h:
            out[-1][1] = h + 1
        else:
            out.append([h, h + 1])
    return out


def _deg_apart(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def panels(state: dict[str, Any], tz: Any, lat: float, lon: float) -> dict[str, Any]:
    """For the settings: which way the panels face (once sure), shaded hours, and whether the forecast agrees."""
    days = state.get("clear_days") or []
    out: dict[str, Any] = {"days": len(days), "need": SURE_DAYS, "sure": False}
    if len(days) < SURE_DAYS:
        return out
    cache: dict = {}
    real = fit(days, "real", tz, lat, lon, cache)
    if not real or real["err"] > 0.35:
        return out  # the days don't fit any panels well (several arrays, odd shade): nothing is claimed
    out.update(sure=True, az=real["az"], ew=real["ew"], tilt=real["tilt"], shade=spans(real["shade"]))
    fc = fit(days, "fc", tz, lat, lon, cache)
    if fc and fc["days"] >= SURE_DAYS and fc["err"] <= 0.35:
        out["forecast"] = {"az": fc["az"], "ew": fc["ew"]}
        if real["ew"] != fc["ew"]:
            out["mismatch"] = True
        elif real["ew"]:
            out["mismatch"] = min(_deg_apart(real["az"], fc["az"]), _deg_apart(real["az"], fc["az"] + 180)) >= MISMATCH_DEG
        else:
            out["mismatch"] = _deg_apart(real["az"], fc["az"]) >= MISMATCH_DEG
    return out

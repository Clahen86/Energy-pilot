"""Storm watch (off unless the user turns it on): a storm or a thunderstorm on its way, and the battery is filled up
before it - in the cheapest hours before the storm, like any other charging; only what the cheap hours can't reach is
bought dearer. While it lasts the battery is kept high, so the house has power if the grid goes down. Afterwards: the
normal plan again.

A storm: gusts of at least the chosen strength (25 m/s unless changed) or a thunderstorm in the weather forecast
(Open-Meteo) within the next 36 hours - or a weather warning in Home Assistant (Meteoalarm, DMI …) that is on.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

GUST_MS = 25.0
FULL, HOLD = 100.0, 80.0
AHEAD_H = 36
WARN_WORDS = ("wind", "storm", "thunder", "torden", "blæst", "orkan", "gale", "sturm", "gewitter", "vent", "orage")


def _warning(states: dict[str, Any]) -> bool:
    """A weather warning in Home Assistant that is on now (Meteoalarm, DMI, MET Norway …) about wind or thunder."""
    for e, st in (states or {}).items():
        if not e.startswith("binary_sensor.") or st.get("state") != "on":
            continue
        a = st.get("attributes") or {}
        txt = " ".join(str(a.get(k) or "") for k in ("event", "headline", "awareness_type", "description", "friendly_name")).lower()
        if ("alarm" in e or "warning" in e or "varsel" in e or a.get("awareness_level")) and any(w in txt for w in WARN_WORDS):
            level = str(a.get("awareness_level") or a.get("severity") or "").lower()
            if not level or any(x in level for x in ("orange", "red", "severe", "extreme", "3", "4")):
                return True
    return False


def find(weather: Any, now: datetime, s: dict[str, Any], states: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The coming storm: {"from", "to", "gust" (m/s), "kind"} - the first window within 36 hours, or None."""
    thr = float(s.get("storm_gust") or GUST_MS)
    hours = sorted((getattr(weather, "hours", None) or {}).items())
    hit = []
    for t, w in hours:
        if t + timedelta(hours=1) <= now or t > now + timedelta(hours=AHEAD_H):
            continue
        gust = (float(w["gust"]) / 3.6) if w.get("gust") is not None else 0.0
        thunder = w.get("code") is not None and int(w["code"]) >= 95
        if gust >= thr or thunder:
            hit.append((t, gust, thunder))
    warn = _warning(states or {})
    if not hit and not warn:
        return None
    if not hit:  # only the warning: from now, the next 12 hours
        return {"from": now.isoformat(), "to": (now + timedelta(hours=12)).isoformat(), "gust": None, "kind": "warning"}
    first, end, top, thunder = hit[0][0], hit[0][0], 0.0, False
    for t, g, th in hit:
        if t - end > timedelta(hours=2):
            break  # the first storm only
        end, top, thunder = t, max(top, g), thunder or th
    return {"from": first.isoformat(), "to": (end + timedelta(hours=1)).isoformat(), "gust": round(top, 1) if top else None,
            "kind": "wind" if top >= thr else "thunder", "warning": warn}


def targets(storm: dict[str, Any] | None, s: dict[str, Any]) -> tuple:
    """The battery's levels for the planner: full when the storm comes, and kept high every hour while it lasts."""
    if not storm:
        return ()
    full = float(s.get("storm_soc") or FULL)
    hold = min(full, float(s.get("storm_hold") or HOLD))
    t0, t1 = datetime.fromisoformat(storm["from"]), datetime.fromisoformat(storm["to"])
    out = [(t0, full)]
    t = t0 + timedelta(hours=1)
    while t <= t1:
        out.append((t, hold))
        t += timedelta(hours=1)
    return tuple(out)

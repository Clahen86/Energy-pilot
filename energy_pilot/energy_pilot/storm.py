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
# The weather services' own warnings in Home Assistant - by integration (the entity registry), else by the entity's name.
WARN_PLATFORMS = {"meteoalarm", "dwd_weather_warnings", "meteo_france", "environment_canada", "gdacs", "nws_alerts",
                  "bureau_of_meteorology", "metservice", "met_alerts", "metoffice_warnings", "uk_weather_warnings", "nhc",
                  "nhc_atlantic", "noaa_alerts"}
WARN_IDS = ("meteoalarm", "warning", "warnings", "alert", "alerts", "varsel", "farevarsel", "nws", "bom_", "gdacs", "nhc", "weather_alert")
STORM_WORDS = ("wind", "storm", "gale", "thunder", "hurricane", "cyclone", "typhoon", "tornado", "blizzard", "squall", "gust",
               "sturm", "orkan", "gewitter", "böe", "boe", "vent violent", "orage", "tempête", "tempete", "vind", "torden", "blæst",
               "uvær", "uvaer", "åska", "aska", "kuling")
SERIOUS = ("orange", "red", "rouge", "severe", "extreme", "major", "warning", "hurricane", "cyclone", "typhoon", "unwetter", "markant")
MILD_ONLY = ("advisory", "yellow", "jaune", "gelb", "gul", "minor", "moderate")


def _text(v) -> str:
    import json

    try:
        return json.dumps(v, ensure_ascii=False, default=str).lower()
    except (TypeError, ValueError):
        return str(v).lower()


def _serious(txt: str) -> bool:
    if not any(w in txt for w in STORM_WORDS):
        return False
    return any(w in txt for w in SERIOUS)


def _start(a: dict) -> str | None:
    for k in ("onset", "Onset", "start", "warning_1_start", "effective", "begin", "from"):
        if a.get(k):
            return str(a[k])
    for x in a.get("Alerts") or a.get("alerts") or a.get("warnings") or []:
        if isinstance(x, dict):
            for k in ("Onset", "onset", "start_time", "issue_time", "start"):
                if x.get(k):
                    return str(x[k])
    return None


def _warning(states: dict[str, Any], reg: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """A serious warning about wind, storm, thunder or a cyclone from the weather service, through Home Assistant:
    Meteoalarm (most of Europe), DWD (DE), Météo-France, Environment Canada, GDACS (cyclones, the whole world), NWS
    Alerts (US), BOM (AU), MetService (NZ), MET Varsler (NO), Met Office warnings (UK), NHC (hurricanes)."""
    reg = reg or {}
    for e, st in (states or {}).items():
        dom = e.split(".")[0]
        if dom not in ("binary_sensor", "sensor", "geo_location"):
            continue
        plat = (reg.get(e) or {}).get("platform")
        if plat not in WARN_PLATFORMS and not any(w in e for w in WARN_IDS):
            continue
        a = st.get("attributes") or {}
        state = str(st.get("state") or "").lower()
        if state in ("off", "unknown", "unavailable", "", "0", "none", "vert", "green", "grün", "gruen"):
            continue
        found = None
        if plat == "gdacs" or dom == "geo_location":  # a cyclone near the home
            try:
                near = float(st.get("state")) < 600
            except (TypeError, ValueError):
                near = False
            if near and any(w in _text(a.get("event_type")) for w in ("cyclone", "storm")) and any(w in _text(a.get("alert_level")) for w in ("orange", "red")):
                found = a.get("event_type") or "cyclone"
        elif plat == "dwd_weather_warnings" or "warning_level" in e:  # DWD: 2 = markant, 3 = Unwetter, 4 = extrem
            try:
                lvl = int(float(st.get("state")))
            except (TypeError, ValueError):
                lvl = 0
            kinds = [a.get(f"warning_{i}_type") for i in range(1, 6)]
            names = _text([a.get(f"warning_{i}_name") for i in range(1, 6)])
            if lvl >= 2 and (0 in kinds or 1 in kinds or any(w in names for w in STORM_WORDS)):
                found = a.get("warning_1_name") or "DWD"
        elif plat == "meteo_france" or "weather_alert" in e:  # {"Vent violent": "Orange", "Orages": "Rouge"}
            for k, v in a.items():
                if any(w in str(k).lower() for w in ("vent", "orage", "vague")) and str(v).lower() in ("orange", "rouge"):
                    found = f"{k}: {v}"
        else:  # Meteoalarm, MET, NWS, BOM, MetService, Environment Canada, Met Office, NHC: by their words
            txt = _text(a)
            lvl = _text(a.get("awareness_level") or a.get("severity") or a.get("level") or "")
            if lvl and any(w in lvl for w in MILD_ONLY) and not any(w in lvl for w in ("orange", "red", "severe", "extreme")):
                continue
            if _serious(txt):
                found = a.get("event") or a.get("headline") or a.get("title") or a.get("friendly_name") or e
        if found:
            return {"source": plat or e.split(".")[0], "text": str(found)[:80], "start": _start(a)}
    return None


def find(weather: Any, now: datetime, s: dict[str, Any], states: dict[str, Any] | None = None, reg: dict[str, Any] | None = None) -> dict[str, Any] | None:
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
    warn = _warning(states or {}, reg)
    if not hit and not warn:
        return None
    if not hit:  # only the warning: from its start (else now), the next 12 hours
        t0 = now
        try:
            st0 = datetime.fromisoformat(str(warn.get("start")).replace("Z", "+00:00"))
            if now < st0 < now + timedelta(hours=AHEAD_H):
                t0 = st0.astimezone(now.tzinfo)
        except (TypeError, ValueError):
            pass
        return {"from": t0.isoformat(), "to": (t0 + timedelta(hours=12)).isoformat(), "gust": None, "kind": "warning",
                "source": warn["source"], "text": warn["text"]}
    first, end, top, thunder = hit[0][0], hit[0][0], 0.0, False
    for t, g, th in hit:
        if t - end > timedelta(hours=2):
            break  # the first storm only
        end, top, thunder = t, max(top, g), thunder or th
    return {"from": first.isoformat(), "to": (end + timedelta(hours=1)).isoformat(), "gust": round(top, 1) if top else None,
            "kind": "wind" if top >= thr else "thunder", "warning": bool(warn), "source": (warn or {}).get("source"), "text": (warn or {}).get("text")}


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

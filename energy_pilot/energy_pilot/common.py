"""Shared knowledge: what other Energy Pilots have learned, as a start for a new one.

The report worker adds up, once a day, what installations that share anonymously have learned (the sun's bias per
country and sun source, the battery's round trip per inverter profile and battery type) and hands it out with the
shared fixes. Only groups of at least three installations that agree are handed out. A new installation leans on it
while it has few days of its own and lets go of it as its own learning takes over.
"""
from __future__ import annotations

from typing import Any

OWN_DAYS = 14  # after this many days of its own, an installation uses only what it has learned itself


def _common(ov: Any) -> dict[str, Any]:
    return ((getattr(ov, "settings", None) or {}).get("community") or {}).get("common") or {}


def sun_key(ov: Any) -> str | None:
    src = getattr(ov, "sun_source", None)
    country = ((getattr(getattr(ov, "ha", None), "config", None) or {}).get("country") or "")
    return f"{country}|{src}" if src and country else None


def sun_bias(ov: Any) -> dict[str, Any] | None:
    """{"cloudy", "clear", "n"} for this installation's country and sun source, or None."""
    key = sun_key(ov)
    got = (_common(ov).get("sun") or {}).get(key or "")
    if not isinstance(got, dict):
        return None
    try:
        out = {k: float(got[k]) for k in ("cloudy", "clear")}
    except (KeyError, TypeError, ValueError):
        return None
    if not all(0.3 <= v <= 2.0 for v in out.values()):
        return None
    return {**out, "n": int(got.get("n") or 0)}


def efficiency(ov: Any, profile: str | None, kind: str | None) -> float | None:
    """The round trip other batteries of this type on this inverter profile really give, or None."""
    if not profile or not kind:
        return None
    got = (_common(ov).get("eff") or {}).get(f"{profile}|{kind}")
    try:
        v = float((got or {}).get("eff"))
    except (TypeError, ValueError):
        return None
    return v if 0.7 <= v <= 0.95 else None


def taper(ov: Any, profile: str | None, model: str | None) -> tuple[tuple[float, float], ...]:
    """How batteries of this model on this inverter profile slow down near full: ((from level, share), ...)."""
    if not profile or not model:
        return ()
    got = ((_common(ov).get("taper") or {}).get(f"{profile}|{model}") or {}).get("taper") or []
    out = []
    for item in got:
        try:
            lvl, share = float(item[0]), float(item[1])
        except (TypeError, ValueError, IndexError):
            return ()
        if 50 <= lvl <= 100 and 0.2 <= share <= 1.0:
            out.append((lvl, round(share, 2)))
    return tuple(sorted(out))


def blend(own: float, shared: float | None, days: int) -> float:
    """Own value weighed by its days, the shared one by the rest - all own after OWN_DAYS."""
    if shared is None or days >= OWN_DAYS:
        return own
    w = max(0, days) / OWN_DAYS
    return w * own + (1 - w) * shared


def info(ov: Any, days: int, battery_kwh: float | None = None, car: bool = False, model: str | None = None,
         learned_kwh: float | None = None, nominal_kwh: float | None = None) -> dict[str, Any]:
    """For the panel: shared knowledge in use, houses like this one, and the battery's health against others."""
    sb = sun_bias(ov)
    hl = health(ov, model)
    mine = round(learned_kwh / nominal_kwh, 2) if learned_kwh and nominal_kwh else None
    return {"sun": sb, "days": days, "in_use": bool(sb) and days < OWN_DAYS, "own_days": OWN_DAYS,
            "peers": peers(ov, battery_kwh, car), "health": {"mine": mine, "others": hl} if hl or mine else None}


def peer_key(country: str | None, battery_kwh: float | None, car: bool) -> str | None:
    """The group "houses like this one" - the same as the worker's peerKey."""
    if not country or not battery_kwh or battery_kwh <= 0:
        return None
    import math

    sent = math.floor(battery_kwh * 2 + 0.5) / 2  # as the daily line sends it (half kWh)
    return f"{country}|{math.floor(sent / 5 + 0.5) * 5}|{'car' if car else 'nocar'}"  # JavaScript's Math.round


def peers(ov: Any, battery_kwh: float | None, car: bool) -> dict[str, Any] | None:
    """What houses like this one saved this month (median), and with or without a feature: {"saved", "n", "features"}."""
    country = (getattr(getattr(ov, "ha", None), "config", None) or {}).get("country")
    got = (_common(ov).get("peers") or {}).get(peer_key(country, battery_kwh, car) or "")
    return got if isinstance(got, dict) and isinstance(got.get("saved"), (int, float)) else None


def health(ov: Any, model: str | None) -> dict[str, Any] | None:
    """Usable kWh against the label for this battery model: {"ratio", "n"}."""
    got = (_common(ov).get("health") or {}).get(str(model or ""))
    return got if isinstance(got, dict) and isinstance(got.get("ratio"), (int, float)) else None


def tariff(ov: Any, home: tuple[float, float] | None) -> dict[str, float] | None:
    """The grid tariff (low/high/peak) neighbours in this ~10 km cell typed in - the same grid company, most likely."""
    if not home:
        return None
    from .skynet import cell

    got = (_common(ov).get("tariff") or {}).get(cell(*home))
    try:
        out = {k: float(got[k]) for k in ("low", "high", "peak")}
    except (KeyError, TypeError, ValueError):
        return None
    return out if all(0 <= v <= 5 for v in out.values()) else None

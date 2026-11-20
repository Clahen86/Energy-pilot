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


def blend(own: float, shared: float | None, days: int) -> float:
    """Own value weighed by its days, the shared one by the rest - all own after OWN_DAYS."""
    if shared is None or days >= OWN_DAYS:
        return own
    w = max(0, days) / OWN_DAYS
    return w * own + (1 - w) * shared


def info(ov: Any, days: int) -> dict[str, Any]:
    """For the panel: is shared knowledge in use, and from how many houses."""
    sb = sun_bias(ov)
    return {"sun": sb, "days": days, "in_use": bool(sb) and days < OWN_DAYS, "own_days": OWN_DAYS}

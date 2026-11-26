"""The inverter's own AC power: what can go through it to and from the grid and the house.

A hybrid can fill its battery from the sun (DC) faster than through its AC side, and a big battery on a small
inverter can't charge from the grid or cover the house faster than the inverter's AC rating. Predbat has the owner type
it in (inverter_limit); here it is read by itself - from a "rated power" sensor where the integration has one, else
from the model's name, which nearly always carries it ("SUN2000-8KTL", "SE10K", "X1-Hybrid-5.0kW", "MultiPlus 48/5000").
Nothing found: None, and the plan counts on the battery's own limits as before.
"""

from __future__ import annotations

import re
from typing import Any

LOW_KW, HIGH_KW = 0.8, 50.0  # a house inverter; outside this it is read wrong

# (pattern, factor to kW) - most specific first
_MODEL = [
    (r"\b(\d+(?:\.\d+)?)\s*kw\b", 1.0),  # "X1-Hybrid-5.0kW", "Sunsynk 12kW Inverter"
    (r"\bse\s?(\d+(?:\.\d+)?)k\b", 1.0),  # SolarEdge SE10K
    (r"\bse(\d{4,5})[a-z]?\b", 0.001),  # SolarEdge SE5000H
    (r"\bsun2000-(\d+(?:\.\d+)?)k", 1.0),  # Huawei SUN2000-8KTL
    (r"\bsun-(\d+(?:\.\d+)?)k", 1.0),  # Deye / Sunsynk SUN-12K-SG05LP3
    (r"\bh[13]-(?:pro-)?(\d+(?:\.\d+)?)\b", 1.0),  # FoxESS H1-3.7-E, H3-Pro-20.0
    (r"\bgw(\d+(?:\.\d+)?)k", 1.0),  # GoodWe GW10KL-ET
    # Kostal PLENTICORE plus 7.0, PLENTICORE G3 L 15 - never the generation: "PLENTICORE L G3" has no size in its name
    (r"\bplenticore(?:\s+(?:plus|bi|[lms]|g\d))*\s+(\d+(?:\.\d+)?)\b", 1.0),
    (r"\bsmile-?g3-[tb](\d+)\b", 1.0),  # AlphaESS SMILE-G3-T10
    (r"\bsmile(\d+(?:\.\d+)?)\b", 1.0),  # AlphaESS SMILE5
    (r"\bhybrid\s+(\d+(?:\.\d+)?)\b", 1.0),  # Sigenergy Sigen Hybrid 5.0
    (r"\b\d{2}/(\d{3,5})\b", 0.001),  # Victron MultiPlus-II 48/5000 (VA)
    (r"\bsph\s?(\d{4,5})\b", 0.001),  # Growatt SPH6000
]
_RATED = re.compile(r"(rated|nominal|max(imum)?)_?(ac_?)?(active_?|output_?)?power$|inverter_power_rating$", re.I)
_NOT = re.compile(r"batter|charg|discharg|pv|solar|string|mppt|grid_?charge|feed|export|import|limit", re.I)


def from_model(model: str | None) -> float | None:
    text = str(model or "").lower()
    for pat, k in _MODEL:
        if m := re.search(pat, text):
            kw = float(m.group(1)) * k
            if LOW_KW <= kw <= HIGH_KW:
                return round(kw, 2)
    return None


def from_states(states: dict[str, Any], allowed: set[str] | None = None) -> float | None:
    """A rated-power sensor of the inverter's own integration (allowed: its sensors) - only when exactly one."""
    found = set()
    for e, st in states.items():
        if not e.startswith("sensor.") or allowed is None or e not in allowed:
            continue
        obj = e.split(".", 1)[1]
        if not _RATED.search(obj) or _NOT.search(obj):
            continue
        a = (st or {}).get("attributes") or {}
        unit = str(a.get("unit_of_measurement") or "").lower()
        try:
            v = float((st or {}).get("state"))
        except (TypeError, ValueError):
            continue
        kw = v / 1000 if unit == "w" else v if unit == "kw" else None
        if kw is not None and LOW_KW <= kw <= HIGH_KW:
            found.add(round(kw, 2))
    return found.pop() if len(found) == 1 else None


def ac_kw(model: str | None, states: dict[str, Any], allowed: set[str] | None = None) -> float | None:
    """The inverter's AC power (kW): a rated-power sensor of its integration first, else the model's name."""
    return from_states(states, allowed) or from_model(model)

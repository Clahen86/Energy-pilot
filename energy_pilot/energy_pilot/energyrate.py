"""Power worked out from an energy counter (kWh total): for chargers that give no live power (Monta's "Charged total").

The counter is watched as it rises: the power is the last rise divided by the time it took. When it stops rising for
longer than it normally takes between two updates (at least 10 minutes), the car is taken as not charging (0 W).
"""

from __future__ import annotations

import time
from typing import Any

ENERGY_UNITS = {"kwh": 1000.0, "wh": 1.0, "mwh": 1_000_000.0}
IDLE_MIN_S = 600.0
MAX_W = 50_000.0  # a jump bigger than this (a counter reset, a restart) is not used

# entity_id -> {"wh": last value, "t": when it last rose, "w": power from the last rise, "gap": seconds of that rise}
_SEEN: dict[str, dict[str, float]] = {}


def is_energy(state: dict[str, Any] | None) -> bool:
    unit = str(((state or {}).get("attributes") or {}).get("unit_of_measurement") or "").lower()
    return unit in ENERGY_UNITS


def watts(entity_id: str, state: dict[str, Any] | None, now: float | None = None) -> float | None:
    """W from a kWh/Wh counter; None until it has been seen rising once (or when it can't be read)."""
    try:
        v = float((state or {}).get("state"))
    except (TypeError, ValueError):
        return None
    unit = str(((state or {}).get("attributes") or {}).get("unit_of_measurement") or "").lower()
    wh = v * ENERGY_UNITS.get(unit, 1000.0)
    now = time.time() if now is None else now
    s = _SEEN.get(entity_id)
    if s is None:
        _SEEN[entity_id] = {"wh": wh, "t": now, "w": 0.0, "gap": 0.0, "first": 1.0}
        return 0.0
    if wh < s["wh"]:  # counter reset (new session, a new month)
        _SEEN[entity_id] = {"wh": wh, "t": now, "w": 0.0, "gap": 0.0, "first": 1.0}
        return 0.0
    if wh > s["wh"]:
        gap = now - s["t"]
        w = (wh - s["wh"]) * 3600.0 / gap if gap > 0 else 0.0
        if w > MAX_W:
            w = 0.0  # a jump (missed updates, a restart): not a real power
        _SEEN[entity_id] = {"wh": wh, "t": now, "w": w, "gap": gap, "first": 0.0}
        return w
    if now - s["t"] > max(IDLE_MIN_S, 2.5 * s["gap"]):
        return 0.0
    return s["w"]

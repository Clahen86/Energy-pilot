"""Nobody home for a day or more (the people in Home Assistant): the plan counts on the house using only what runs by
itself (fridge, freezer, standby) - so it doesn't buy power for a family that's away. Back to normal the moment anyone
is home. Nothing to set: people without a tracker are left out, and with no people it never happens."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

AWAY_H = 24


def away_since(states: dict[str, Any]) -> datetime | None:
    """When the last person left - None when someone is home, or nobody is known."""
    known = [s for e, s in states.items() if e.startswith("person.") and s.get("state") not in (None, "unknown", "unavailable")]
    if not known or any(s.get("state") == "home" for s in known):
        return None
    try:
        return max(datetime.fromisoformat(str(s.get("last_changed"))) for s in known)
    except (TypeError, ValueError):
        return None


def is_away(states: dict[str, Any], now: datetime) -> bool:
    since = away_since(states)
    return since is not None and now - since >= timedelta(hours=AWAY_H)


def standby(house: list[float]) -> float | None:
    """What the house uses by itself: its quietest hour of the coming day."""
    return min(house[:24]) if house else None

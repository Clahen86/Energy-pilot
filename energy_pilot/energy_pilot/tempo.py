"""EDF Tempo (France): prices from the day colours - blue, white, red - each with off-peak and peak hours.

A Tempo day runs from 06:00 to 06:00 the next morning; off-peak ("heures creuses") is 22:00-06:00, peak ("heures
pleines") 06:00-22:00. RTE announces tomorrow's colour around 11:00, so the plan can fill the battery the night
before a red day. Read from the integration's own entities (e.g. "Tarif EDF"): today's, tomorrow's and
yesterday's colour, and the six prices. An unknown colour is left out - the plan doesn't guess a red day.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import re
from typing import Any
from zoneinfo import ZoneInfo

COLOURS = {"bleu": "blue", "blue": "blue", "blanc": "white", "white": "white", "rouge": "red", "red": "red"}


def _colour(states: dict[str, dict], when: str) -> dict[str, str]:
    """{"today"/"tomorrow"/"yesterday": entity_id} of the colour sensors."""
    words = {"today": r"aujourd|today", "tomorrow": r"demain|tomorrow", "yesterday": r"hier|yesterday"}
    for e in states:
        if "tempo" in e and re.search(r"couleur|colou?r", e) and re.search(words[when], e):
            return e
    return None


def found(states: dict[str, dict]) -> bool:
    return bool(_colour(states, "today") and prices_by_colour(states))


def prices_by_colour(states: dict[str, dict]) -> dict[tuple[str, str], float]:
    """{("blue", "off"): 0.13, ("red", "peak"): 0.75, …} from the six price sensors."""
    out = {}
    for e, s in states.items():
        o = e.split(".", 1)[-1]
        if "tempo" not in o:
            continue
        c = next((COLOURS[w] for w in COLOURS if re.search(rf"(^|_){w}(_|$)", o)), None)
        part = "off" if re.search(r"creuses|off_?peak|_hc(_|$)", o) else "peak" if re.search(r"pleines|_hp(_|$)|peak", o) else None
        if c and part:
            try:
                out[(c, part)] = float(s.get("state"))
            except (TypeError, ValueError):
                pass
    return out


def colour_of(states: dict[str, dict], when: str) -> str | None:
    e = _colour(states, when)
    v = str((states.get(e) or {}).get("state") or "").strip().lower() if e else ""
    return next((COLOURS[w] for w in COLOURS if w in v), None)


def prices(states: dict[str, dict], tz: ZoneInfo, now: datetime | None = None) -> dict[datetime, float]:
    """Hour by hour from yesterday's 06:00 to the end of the last known Tempo day."""
    now = now or datetime.now(tz)
    table = prices_by_colour(states)
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    out: dict[datetime, float] = {}
    for offset, when in ((-1, "yesterday"), (0, "today"), (1, "tomorrow")):
        c = colour_of(states, when)
        if not c:
            continue
        start = day0 + timedelta(days=offset, hours=6)  # the Tempo day: 06:00 -> 06:00
        for h in range(24):
            t = start + timedelta(hours=h)
            part = "off" if t.hour >= 22 or t.hour < 6 else "peak"
            if (c, part) in table:
                out[t] = table[(c, part)]
    return out

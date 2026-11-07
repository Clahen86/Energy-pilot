"""Is the car in the house's use? Many homes only have a sensor for everything, the car included.

The car is planned on its own, so it must not also be in the house's use: it would count twice, make the house
forecast high and uneven, and the battery would be saved for (and emptied into) the car.

Found from the hours the car charged: if the house's use rose by about as much as the charger took, compared
with the same hours of the day without charging, the car is in it - and is taken out, live and in the history.
"""

from __future__ import annotations

from datetime import datetime
from statistics import median


def detect(house: list[tuple[datetime, float]], ev: list[tuple[datetime, float]]) -> bool | None:
    """True: the car is in the house's use; False: it isn't; None: not enough charging seen to tell."""
    ev_by = {w: kw for w, kw in ev}
    charging = [(w, kw, ev_by[w]) for w, kw in house if ev_by.get(w, 0) >= 1.0]
    quiet: dict[int, list[float]] = {}
    for w, kw in house:
        if ev_by.get(w, 0) < 0.1:
            quiet.setdefault(w.hour, []).append(kw)
    ratios = []
    for w, kw, car in charging:
        base = quiet.get(w.hour)
        if base and len(base) >= 3:
            ratios.append((kw - median(base)) / car)
    if len(ratios) < 3:
        return None
    return median(ratios) > 0.6  # the house rose by most of what the car took


def subtract(house: list[tuple[datetime, float]], ev: list[tuple[datetime, float]]) -> list[tuple[datetime, float]]:
    ev_by = {w: kw for w, kw in ev}
    return [(w, max(0.0, kw - ev_by.get(w, 0.0))) for w, kw in house]

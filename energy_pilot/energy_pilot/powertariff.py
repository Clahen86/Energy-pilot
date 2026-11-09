"""Power tariffs (Belgium's capacity tariff, Norway's and Sweden's "effektavgift"): part of the bill is the month's peak.

The peak is measured over a window (15 minutes in Belgium, an hour elsewhere) and is either the month's highest, or the
average of the highest on three different days (Norway, Sweden). Energy Pilot keeps the month's peaks itself; the plan
then pays a price for every kW above the peak so far, so the battery shaves the peaks and the car charges beside them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

# By country: window in minutes, peaks counted (on different days). The price per kW is the user's own.
PRESETS = {"BE": (15, 1), "NO": (60, 3), "SE": (60, 3)}
FLOOR_KW = 2.0  # early in the month the peak is low - never plan as if 1 kW were the limit


def kind(settings: dict[str, Any], country: str | None) -> tuple[int, int]:
    k = settings.get("power_tariff_kind")
    if k == "15min":
        return 15, 1
    if k == "top3":
        return 60, 3
    if k == "hour":
        return 60, 1
    return PRESETS.get(str(country or "").upper(), (60, 1))


class MonthPeak:
    """The month's peaks (kW over the window), kept in the learning state so a restart keeps them."""

    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state
        self._slot: tuple[datetime, float, int] | None = None  # window start, sum of kW, samples

    def see(self, now: datetime, grid_w: float | None, window_min: int) -> None:
        if grid_w is None:
            return
        start = now.replace(minute=now.minute // window_min * window_min if window_min < 60 else 0, second=0, microsecond=0)
        kw = max(0.0, grid_w) / 1000
        if self._slot and self._slot[0] != start:
            s0, total, n = self._slot
            if n >= 3:
                self._record(s0, total / n)
            self._slot = None
        if self._slot is None:
            self._slot = (start, 0.0, 0)
        s0, total, n = self._slot
        self._slot = (s0, total + kw, n + 1)

    def _record(self, start: datetime, kw: float) -> None:
        m = self.state.setdefault("month_peak", {})
        month = start.strftime("%Y-%m")
        if m.get("month") != month:
            if m.get("month"):
                m["last_level"] = self.level()  # last month's, a guide for the first days of the new one
            m["month"], m["peaks"] = month, {}
        day = start.strftime("%d")
        peaks = m.setdefault("peaks", {})
        if kw > peaks.get(day, 0.0):
            peaks[day] = round(kw, 2)

    def level(self, count: int | None = None) -> float | None:
        """What the bill is based on so far: the highest, or the average of the highest days."""
        m = self.state.get("month_peak") or {}
        vals = sorted((m.get("peaks") or {}).values(), reverse=True)
        if not vals:
            return None
        n = count or m.get("count") or 1
        top = vals[:n]
        return round(sum(top) / len(top), 2)

    def limit(self, count: int) -> float:
        """The peak the plan tries to stay under: this month's so far, at least a share of last month's and 2 kW."""
        m = self.state.setdefault("month_peak", {})
        m["count"] = count
        now = self.level(count) or 0.0
        last = float(m.get("last_level") or 0.0) * 0.8
        return round(max(now, last, FLOOR_KW), 2)

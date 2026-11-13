"""The house's own use per hour, kept by Energy Pilot itself - for homes where Home Assistant keeps no statistics of
the house sensor (no state_class), so there is no history to learn from. Kept for 60 days, saved with the learning."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

KEEP_DAYS = 60


class HouseHistory:
    def __init__(self, state: dict[str, Any]) -> None:
        self.s = state.setdefault("house_hist", {})
        self._hour: str | None = None
        self._sum, self._n = 0.0, 0

    def see(self, now: datetime, house_w: float | None) -> None:
        """Every half minute: the house's use now (W, without the car). A whole hour's mean is kept as kW."""
        if house_w is None or house_w < 0:
            return
        hour = now.replace(minute=0, second=0, microsecond=0).isoformat()
        if hour != self._hour:
            if self._hour is not None and self._n >= 60:  # most of the hour seen (120 rounds in an hour)
                self.s[self._hour] = round(self._sum / self._n / 1000, 3)
                cut = (now - timedelta(days=KEEP_DAYS)).isoformat()
                for k in [k for k in self.s if k < cut]:
                    del self.s[k]
            self._hour, self._sum, self._n = hour, 0.0, 0
        self._sum += house_w
        self._n += 1

    def rows(self) -> list[tuple[datetime, float]]:
        return [(datetime.fromisoformat(k), v) for k, v in sorted(self.s.items())]

    def days(self) -> int:
        return len(self.s) // 24

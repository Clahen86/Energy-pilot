"""A new plan as soon as the prices change - not up to 5 minutes later.

Some tariffs change the rest of today's prices at any moment (Octopus Intelligent gives cheap slots while the car
charges). The engine round normally runs every 5 minutes; this wakes it when a price entity changes."""
from __future__ import annotations

import asyncio
import time
from typing import Any

from .pricefeed import companions


class Replan:
    GAP = 60.0  # at most one extra round a minute
    SETTLE = 5.0  # the integration updates its entities one after another: wait until all are in

    def __init__(self, ha: Any, ov: Any) -> None:
        self.ha, self.ov = ha, ov
        self.wake = asyncio.Event()
        self.watched: set[str] = set()
        self._last = float("-inf")  # the first change wakes the round at once (monotonic time can start low)
        self._pending = False
        ha.on_state.append(self.on_state)

    def refresh(self) -> None:
        """Which entities hold prices - asked each round, as the user can pick another price entity."""
        out: set[str] = set()
        for role in ("price", "sell_price"):
            if e := self.ov.role(role):
                out.add(e)
                try:
                    out.update(companions(self.ha.states, e))
                except Exception:  # noqa: BLE001
                    pass
        self.watched = out

    @staticmethod
    def _key(s: dict | None) -> Any:
        if not s:
            return None
        return s.get("state"), {k: v for k, v in (s.get("attributes") or {}).items() if k not in ("last_updated", "last_changed")}

    def on_state(self, entity_id: str, old: dict | None, new: dict | None) -> None:
        if entity_id not in self.watched or self._pending or old is None:
            return
        if self._key(old) == self._key(new):
            return
        self._pending = True
        delay = max(self.SETTLE, self.GAP - (time.monotonic() - self._last))
        try:
            asyncio.get_running_loop().call_later(delay, self._fire)
        except RuntimeError:
            self._pending = False

    def _fire(self) -> None:
        self._pending = False
        self.wake.set()

    async def sleep(self, seconds: float) -> bool:
        """Sleep until the next round - or until the prices change. True when woken by a price change."""
        try:  # a change during the round itself still wakes the next one at once
            await asyncio.wait_for(self.wake.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            return False
        self.wake.clear()
        self._last = time.monotonic()
        return True

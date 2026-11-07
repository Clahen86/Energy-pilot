"""When the car must be ready."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity

from .entity import PilotEntity


async def async_setup_entry(hass, entry, add):
    if entry.runtime_data.data.get("ev") is not None:
        add([ReadyAt(entry.runtime_data)])


class ReadyAt(PilotEntity, TimeEntity):
    def __init__(self, p):
        super().__init__(p, "ready_at")

    @property
    def native_value(self):
        v = (self.d.get("ev") or {}).get("ready")
        try:
            h, m = (int(x) for x in str(v).split(":")[:2])
            return time(h, m)
        except (TypeError, ValueError):
            return None

    async def async_set_value(self, value: time) -> None:
        await self.coordinator.post("/api/ev", {"ready": value.strftime("%H:%M:00")})

"""When the car must be ready."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity

from .entity import CarEntity, PilotEntity, cars


async def async_setup_entry(hass, entry, add):
    if entry.runtime_data.data.get("ev") is not None:
        add([ReadyAt(entry.runtime_data)])
    add([CarReady(entry.runtime_data, c) for c in cars(entry.runtime_data)])


def _hm(v):
    try:
        h, m = (int(x) for x in str(v).split(":")[:2])
        return time(h, m)
    except (TypeError, ValueError):
        return None


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


class CarReady(CarEntity, TimeEntity):
    def __init__(self, p, car):
        super().__init__(p, "ready_at", car)

    @property
    def native_value(self):
        return _hm(self.car.get("ready"))

    async def async_set_value(self, value: time) -> None:
        await self.send({"ready": value.strftime("%H:%M")})

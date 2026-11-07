"""The style: cheapest, most sun, safety, car first, battery first."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity

from .entity import PilotEntity

STYLES = ["cheapest", "solar", "safe", "car_first", "battery_first"]


async def async_setup_entry(hass, entry, add):
    add([Style(entry.runtime_data)])


class Style(PilotEntity, SelectEntity):
    _attr_options = STYLES

    def __init__(self, p):
        super().__init__(p, "style")

    @property
    def current_option(self):
        return self.s.get("style") or "cheapest"

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.post("/api/settings", {"style": option})

"""The style: cheapest, most sun, safety, car first, battery first. And who decides for the battery and the car:
shadow (only shows), control (sends it) or off - so an automation can switch Energy Pilot on and off."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity

from .entity import PilotEntity

STYLES = ["cheapest", "solar", "safe", "car_first", "battery_first"]


async def async_setup_entry(hass, entry, add):
    p = entry.runtime_data
    parts = (p.data or {}).get("control") or {}
    add([Style(p)] + [Mode(p, part) for part in ("battery", "car") if part in parts])


class Style(PilotEntity, SelectEntity):
    _attr_options = STYLES

    def __init__(self, p):
        super().__init__(p, "style")

    @property
    def current_option(self):
        return self.s.get("style") or "cheapest"

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.post("/api/settings", {"style": option})


class Mode(PilotEntity, SelectEntity):
    _attr_options = ["shadow", "control", "off"]

    def __init__(self, p, part: str):
        super().__init__(p, f"{part}_mode")
        self.part = part

    @property
    def current_option(self):
        return ((self.d.get("control") or {}).get(self.part) or {}).get("mode")

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.post("/api/control", {"part": self.part, "mode": option})

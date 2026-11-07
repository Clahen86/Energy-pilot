"""Everything back to shadow - one press stops all control."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity

from .entity import PilotEntity


async def async_setup_entry(hass, entry, add):
    add([AllShadow(entry.runtime_data)])


class AllShadow(PilotEntity, ButtonEntity):
    def __init__(self, p):
        super().__init__(p, "all_shadow")

    async def async_press(self) -> None:
        await self.coordinator.post("/api/shadow_all", {})

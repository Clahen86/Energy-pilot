"""Charge the car now."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity

from .entity import PilotEntity


async def async_setup_entry(hass, entry, add):
    ev = entry.runtime_data.data.get("ev")
    if ev is not None:
        add([ChargeNow(entry.runtime_data)] + ([NextTrip(entry.runtime_data)] if ev.get("soc_known") else []))


class ChargeNow(PilotEntity, SwitchEntity):
    def __init__(self, p):
        super().__init__(p, "charge_now")

    @property
    def is_on(self):
        return bool((self.d.get("ev") or {}).get("manual"))

    async def async_turn_on(self, **kwargs):
        await self.coordinator.post("/api/ev", {"manual": True})

    async def async_turn_off(self, **kwargs):
        await self.coordinator.post("/api/ev", {"manual": False})


class NextTrip(PilotEntity, SwitchEntity):
    """100 % for the next trip - turns itself off when the car leaves full."""

    def __init__(self, p):
        super().__init__(p, "next_trip")

    @property
    def is_on(self):
        return bool((self.d.get("ev") or {}).get("trip"))

    async def async_turn_on(self, **kwargs):
        await self.coordinator.post("/api/ev", {"trip": True})

    async def async_turn_off(self, **kwargs):
        await self.coordinator.post("/api/ev", {"trip": False})

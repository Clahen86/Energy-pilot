"""Common base: one device, "Energipilot"."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN, Pilot


class PilotEntity(CoordinatorEntity[Pilot]):
    _attr_has_entity_name = True

    def __init__(self, pilot: Pilot, key: str) -> None:
        super().__init__(pilot)
        self._attr_translation_key = key
        self._attr_unique_id = f"{DOMAIN}_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, "pilot")}, name="Energipilot", manufacturer="Energipilot")

    @property
    def d(self) -> dict:
        return self.coordinator.data or {}

    @property
    def s(self) -> dict:
        return self.d.get("settings_full") or {}

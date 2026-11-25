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
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, "pilot")}, name="Energy Pilot", manufacturer="Energy Pilot")

    @property
    def d(self) -> dict:
        return self.coordinator.data or {}

    @property
    def s(self) -> dict:
        return self.d.get("settings_full") or {}


def cars(pilot: Pilot) -> list[dict]:
    """The extra cars (charger 2, 3 …) as the app shows them."""
    return (pilot.data or {}).get("cars") or []


class CarEntity(PilotEntity):
    """One of an extra car's entities: the same as the first car's, named after the car ("Tesla: Charge now")."""

    def __init__(self, pilot: Pilot, key: str, car: dict) -> None:
        super().__init__(pilot, f"car_{key}")
        self.n = car["n"]
        self._attr_unique_id = f"{DOMAIN}_car{self.n}_{key}"
        self._attr_translation_placeholders = {"car": car.get("name") or f"Car {self.n}"}
        self._attr_extra_state_attributes = {"ep_car": self.n, "ep_key": key}  # the dashboard card finds its buttons by these

    @property
    def car(self) -> dict:
        return next((c for c in self.d.get("cars") or [] if c.get("n") == self.n), {})

    async def send(self, body: dict) -> None:
        await self.coordinator.post("/api/charger", {"n": self.n, **body})

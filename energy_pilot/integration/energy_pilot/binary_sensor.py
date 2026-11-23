"""Something needs a look: a warning in Energy Pilot's own check, or it can't reach Home Assistant - for a notification."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity

from .entity import PilotEntity


async def async_setup_entry(hass, entry, add):
    add([Problem(entry.runtime_data)])


class Problem(PilotEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, p):
        super().__init__(p, "problem")

    @property
    def is_on(self):
        return bool((self.d.get("problem") or {}).get("on"))

    @property
    def extra_state_attributes(self):
        return {"checks": (self.d.get("problem") or {}).get("keys") or []}

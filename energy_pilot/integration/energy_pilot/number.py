"""At most kWh per charge, and the battery's minimum."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE, UnitOfEnergy

from .entity import PilotEntity


async def async_setup_entry(hass, entry, add):
    p = entry.runtime_data
    items = [BatteryMin(p)] if (p.data.get("flow") or {}).get("soc") is not None else []
    if p.data.get("ev") is not None:
        items.append(AtMost(p))
        if (p.data.get("ev") or {}).get("soc_known"):
            items.append(ChargeTo(p))
    add(items)


class AtMost(PilotEntity, NumberEntity):
    _attr_native_min_value, _attr_native_max_value, _attr_native_step = 0, 100, 1
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_mode = NumberMode.SLIDER

    def __init__(self, p):
        super().__init__(p, "at_most")

    @property
    def native_value(self):
        return (self.d.get("ev") or {}).get("cap")

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.post("/api/ev", {"cap": value})


class BatteryMin(PilotEntity, NumberEntity):
    _attr_native_min_value, _attr_native_max_value, _attr_native_step = 5, 60, 5
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    def __init__(self, p):
        super().__init__(p, "battery_min")

    @property
    def native_value(self):
        return self.s.get("battery_min_soc") or 10

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.post("/api/settings", {"battery_min_soc": value})


class ChargeTo(PilotEntity, NumberEntity):
    """The car's everyday target (%): 80 % spares the battery."""

    _attr_native_min_value, _attr_native_max_value, _attr_native_step = 20, 100, 5
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    def __init__(self, p):
        super().__init__(p, "charge_to")

    @property
    def native_value(self):
        return (self.d.get("ev") or {}).get("everyday")

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.post("/api/ev", {"target": int(value)})

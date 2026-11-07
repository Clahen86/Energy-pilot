"""What the engine decides, the price now, the battery's target, what the plan saves, what it learned yesterday."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE

from .entity import PilotEntity


async def async_setup_entry(hass, entry, add):
    p = entry.runtime_data
    add([Decision(p), PriceNow(p), Target(p), Saving(p), Yesterday(p),
         Saved(p, "saved_today", "today"), Saved(p, "saved_month", "month"), Saved(p, "saved_year", "year"),
         Saved(p, "saved_total", "total"), BatteryCost(p)])


class Decision(PilotEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["discharge", "charge", "grid", "hold"]

    def __init__(self, p):
        super().__init__(p, "decision")

    @property
    def native_value(self):
        return (self.d.get("decision") or {}).get("kind")

    @property
    def extra_state_attributes(self):
        dec = self.d.get("decision") or {}
        return {"text": dec.get("text"), "reason": dec.get("reason")}


class PriceNow(PilotEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.MONETARY

    def __init__(self, p):
        super().__init__(p, "price_now")

    @property
    def native_unit_of_measurement(self):
        return f"{self.d.get('currency') or 'DKK'}/kWh"

    @property
    def native_value(self):
        return (self.d.get("price") or {}).get("now")


class Target(PilotEntity, SensorEntity):
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, p):
        super().__init__(p, "battery_target")

    @property
    def native_value(self):
        return (self.d.get("decision") or {}).get("target")


class Saving(PilotEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.MONETARY

    def __init__(self, p):
        super().__init__(p, "plan_saving")

    @property
    def native_unit_of_measurement(self):
        return self.d.get("currency") or "DKK"

    @property
    def native_value(self):
        return (self.d.get("engine") or {}).get("saving")


class Yesterday(PilotEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.MONETARY

    def __init__(self, p):
        super().__init__(p, "saved_yesterday")

    @property
    def native_unit_of_measurement(self):
        return self.d.get("currency") or "DKK"

    @property
    def native_value(self):
        y = (((self.d.get("engine") or {}).get("learning") or {}).get("yesterday") or {})
        return y.get("saving")


class Saved(PilotEntity, SensorEntity):
    """Measured: what the battery saved today / this month / this year / in all."""

    _attr_device_class = SensorDeviceClass.MONETARY

    def __init__(self, p, key, period):
        super().__init__(p, key)
        self.period = period
        if period == "total":
            self._attr_state_class = SensorStateClass.TOTAL  # only "in all" never starts over

    @property
    def native_unit_of_measurement(self):
        return self.d.get("currency") or "DKK"

    @property
    def native_value(self):
        return (self.d.get("ledger") or {}).get(self.period)


class BatteryCost(PilotEntity, SensorEntity):
    """What the power in the battery cost per kWh."""

    _attr_suggested_display_precision = 2

    def __init__(self, p):
        super().__init__(p, "battery_cost")

    @property
    def native_unit_of_measurement(self):
        return f"{self.d.get('currency') or 'DKK'}/kWh"

    @property
    def native_value(self):
        return (self.d.get("ledger") or {}).get("avg_cost")

    @property
    def extra_state_attributes(self):
        g = self.d.get("ledger") or {}
        return {"kwh": g.get("battery_kwh", g.get("stored_kwh")), "source": g.get("avg_source")}

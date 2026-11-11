"""What the engine decides, the price now, the battery's target, what the plan saves, what it learned yesterday."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfEnergy
from homeassistant.util import dt as dt_util

from .entity import PilotEntity


async def async_setup_entry(hass, entry, add):
    p = entry.runtime_data
    add([Decision(p), PriceNow(p), Target(p), Saving(p), Yesterday(p),
         Saved(p, "saved_today", "today"), Saved(p, "saved_month", "month"), Saved(p, "saved_year", "year"),
         Saved(p, "saved_total", "total"), BatteryCost(p),
         NextSlot(p, "next_battery_charge", "charge"), NextSlot(p, "next_car_charge", "car"), NextSlot(p, "next_battery_sell", "export"),
         Cheapest(p), Energy(p, "house_today", lambda d: d.get("house_today")),
         Energy(p, "solar_forecast_today", lambda d: (d.get("solar") or {}).get("solar_today")),
         Energy(p, "solar_forecast_tomorrow", lambda d: (d.get("solar") or {}).get("solar_tomorrow"))])


def _hours(d: dict) -> list[tuple[datetime, dict]]:
    """The plan's coming slots (the one now included), as times."""
    out = []
    now = dt_util.now()
    hours = (d.get("plan") or {}).get("hours") or []
    for i, h in enumerate(hours):
        t = dt_util.parse_datetime(str(h.get("t")))
        nxt = dt_util.parse_datetime(str(hours[i + 1]["t"])) if i + 1 < len(hours) else None
        if t and (nxt or t) > now:
            out.append((t, h))
    return out


class NextSlot(PilotEntity, SensorEntity):
    """When the plan next charges the battery from the grid, charges the car, or sells from the battery - for your own
    automations. Empty when nothing is planned in the coming hours."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, p, key, flag):
        super().__init__(p, key)
        self.flag = flag

    def _block(self):
        slots = _hours(self.d)
        for i, (t, h) in enumerate(slots):
            if h.get(self.flag):
                j = i
                while j + 1 < len(slots) and slots[j + 1][1].get(self.flag):
                    j += 1
                step = (slots[1][0] - slots[0][0]) if len(slots) > 1 else None
                end = slots[j + 1][0] if j + 1 < len(slots) else (slots[j][0] + step if step else None)
                return t, end, slots[j][1]
        return None

    @property
    def native_value(self):
        b = self._block()
        return b[0] if b else None

    @property
    def extra_state_attributes(self):
        b = self._block()
        if not b:
            return {"until": None}
        out = {"until": b[1].isoformat() if b[1] else None}
        if b[2].get("soc") is not None:
            out["battery_level"] = b[2]["soc"]
        return out


class Cheapest(PilotEntity, SensorEntity):
    """The start of the next of the cheapest hours (for the dishwasher and the like) - all of them as an attribute."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, p):
        super().__init__(p, "cheapest_hour")

    def _coming(self):
        now = dt_util.now()
        ts = [dt_util.parse_datetime(str(t)) for t in (self.d.get("plan") or {}).get("cheapest") or []]
        return sorted(t for t in ts if t and t.timestamp() + 3600 > now.timestamp())

    @property
    def native_value(self):
        c = self._coming()
        return c[0] if c else None

    @property
    def extra_state_attributes(self):
        return {"hours": [t.isoformat() for t in self._coming()]}


class Energy(PilotEntity, SensorEntity):
    """The house's use today so far, and the solar forecast for today and tomorrow (kWh)."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 1

    def __init__(self, p, key, get):
        super().__init__(p, key)
        self.get = get
        if key == "house_today":
            self._attr_state_class = SensorStateClass.TOTAL_INCREASING  # starts over at midnight

    @property
    def native_value(self):
        v = self.get(self.d)
        return round(float(v), 2) if isinstance(v, (int, float)) else None


class Decision(PilotEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["discharge", "charge", "grid", "hold", "export"]

    def __init__(self, p):
        super().__init__(p, "decision")

    @property
    def native_value(self):
        kind = (self.d.get("decision") or {}).get("kind")
        # A state Home Assistant doesn't know is refused, and the sensor would keep showing the last one.
        return kind if kind in self._attr_options else None

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

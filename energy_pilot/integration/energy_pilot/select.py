"""The style: cheapest, most sun, safety, car first, battery first. And who decides for the battery and the car:
shadow (only shows), control (sends it) or off - so an automation can switch Energy Pilot on and off."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity

from .entity import CarEntity, PilotEntity, cars

STYLES = ["cheapest", "solar", "safe", "car_first", "battery_first"]


async def async_setup_entry(hass, entry, add):
    p = entry.runtime_data
    parts = (p.data or {}).get("control") or {}
    add([Style(p)] + [Mode(p, part) for part in ("battery", "car") if part in parts])
    # more cars than chargers: which car is in each charger (found by itself; pick it here or in an automation)
    if ((p.data or {}).get("ev") or {}).get("car"):
        add([CarIn(p)])
    add([CarInExtra(p, c) for c in cars(p) if c.get("car")])


def _names(view: dict | None) -> list[str]:
    return [c.get("name") or f"Car {i + 1}" for i, c in enumerate((view or {}).get("choices") or [])]


def _current(view: dict | None) -> str | None:
    for i, c in enumerate((view or {}).get("choices") or []):
        if c.get("id") == (view or {}).get("id"):
            return c.get("name") or f"Car {i + 1}"
    return None


def _id(view: dict | None, option: str) -> str | None:
    for i, c in enumerate((view or {}).get("choices") or []):
        if (c.get("name") or f"Car {i + 1}") == option:
            return c.get("id")
    return None


class CarIn(PilotEntity, SelectEntity):
    """Which car is in charger 1."""

    _attr_extra_state_attributes = {"ep_car": 1, "ep_key": "car_in"}

    def __init__(self, p):
        super().__init__(p, "car_in")

    @property
    def options(self):
        return _names((self.d.get("ev") or {}).get("car"))

    @property
    def current_option(self):
        return _current((self.d.get("ev") or {}).get("car"))

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.post("/api/car_in", {"part": "car", "car": _id((self.d.get("ev") or {}).get("car"), option)})


class CarInExtra(CarEntity, SelectEntity):
    """Which car is in an extra charger."""

    def __init__(self, p, car):
        super().__init__(p, "car_in", car)

    @property
    def options(self):
        return _names(self.car.get("car"))

    @property
    def current_option(self):
        return _current(self.car.get("car"))

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.post("/api/car_in", {"part": f"car{self.n}", "car": _id(self.car.get("car"), option)})


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

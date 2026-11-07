"""Energipilot in Home Assistant: buttons and sensors for the Energy Pilot app (it does the thinking)."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

_LOGGER = logging.getLogger(__name__)
DOMAIN = "energy_pilot"
PLATFORMS = [Platform.BUTTON, Platform.NUMBER, Platform.SELECT, Platform.SENSOR, Platform.SWITCH, Platform.TIME]


class Pilot(DataUpdateCoordinator[dict[str, Any]]):
    """Asks the app every 15 seconds; sends what the buttons are set to."""

    def __init__(self, hass: HomeAssistant, url: str) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=timedelta(seconds=15))
        self.url = url.rstrip("/")
        self.session = async_get_clientsession(hass)

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            async with self.session.get(f"{self.url}/api/overview", timeout=aiohttp.ClientTimeout(total=10)) as r:
                r.raise_for_status()
                data = await r.json()
            async with self.session.get(f"{self.url}/api/settings", timeout=aiohttp.ClientTimeout(total=10)) as r:
                data["settings_full"] = (await r.json()).get("settings", {})
            return data
        except (aiohttp.ClientError, TimeoutError) as err:
            raise UpdateFailed(f"Energy Pilot isn't answering: {err}") from err

    async def post(self, path: str, body: dict[str, Any]) -> None:
        async with self.session.post(f"{self.url}{path}", json=body, timeout=aiohttp.ClientTimeout(total=20)) as r:
            r.raise_for_status()
        await self.async_request_refresh()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    pilot = Pilot(hass, entry.data["url"])
    await pilot.async_config_entry_first_refresh()
    entry.runtime_data = pilot
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

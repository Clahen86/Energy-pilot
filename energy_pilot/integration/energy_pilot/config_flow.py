"""Found by itself when the app runs in Home Assistant; in Docker, give the app's address."""

from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from . import DOMAIN


class EnergyPilotFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._url: str | None = None

    async def _ok(self, url: str) -> bool:
        try:
            async with async_get_clientsession(self.hass).get(f"{url.rstrip('/')}/api/overview", timeout=aiohttp.ClientTimeout(total=8)) as r:
                return r.status == 200
        except (aiohttp.ClientError, TimeoutError):
            return False

    async def async_step_hassio(self, discovery_info: HassioServiceInfo) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        cfg = discovery_info.config
        self._url = f"http://{cfg['host']}:{cfg['port']}"
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="Energipilot", data={"url": self._url})
        return self.async_show_form(step_id="confirm")

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors = {}
        if user_input is not None:
            if await self._ok(user_input["url"]):
                return self.async_create_entry(title="Energipilot", data={"url": user_input["url"].rstrip("/")})
            errors["base"] = "cannot_connect"
        return self.async_show_form(step_id="user", data_schema=vol.Schema({vol.Required("url", default="http://homeassistant.local:8099"): str}),
                                    errors=errors)

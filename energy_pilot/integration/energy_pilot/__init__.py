"""Energipilot in Home Assistant: buttons and sensors for the Energy Pilot app (it does the thinking)."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

import aiohttp

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

_LOGGER = logging.getLogger(__name__)
DOMAIN = "energy_pilot"
PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.NUMBER, Platform.SELECT, Platform.SENSOR, Platform.SWITCH, Platform.TIME]
CARD_URL = "/energy_pilot/energipilot-card.js"
OLD_CARD = "/local/energipilot/"  # where the app put the card before (it needed write access to Home Assistant's folder)


class CardView(HomeAssistantView):
    """The dashboard card, fetched from the app - so it follows the app's version, and the app needs no access to
    Home Assistant's folder. Public like any other card file (a script, no data)."""

    url = CARD_URL
    name = "energy_pilot:card"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:
        entries = self.hass.config_entries.async_entries(DOMAIN)
        if not entries:
            return web.Response(status=404)
        url = entries[0].data["url"].rstrip("/")
        try:
            async with async_get_clientsession(self.hass).get(f"{url}/static/energipilot-card.js", timeout=aiohttp.ClientTimeout(total=10)) as r:
                r.raise_for_status()
                body = await r.read()
        except (aiohttp.ClientError, TimeoutError):
            return web.Response(status=503, text="// Energy Pilot isn't answering", content_type="application/javascript")
        return web.Response(body=body, content_type="application/javascript", headers={"Cache-Control": "no-cache"})


async def _card(hass: HomeAssistant) -> None:
    """Serve the card and load it on every dashboard; drop the old copy's resource the app made in /local/."""
    from homeassistant.components.frontend import add_extra_js_url

    if hass.data.setdefault(DOMAIN, {}).get("card"):
        return
    hass.http.register_view(CardView(hass))
    add_extra_js_url(hass, CARD_URL)
    hass.data[DOMAIN]["card"] = True
    try:
        ll = hass.data.get("lovelace")
        res = getattr(ll, "resources", None) or (ll.get("resources") if isinstance(ll, dict) else None)
        if res is None or not hasattr(res, "async_items"):
            return
        if not getattr(res, "loaded", True):
            await res.async_load()
            res.loaded = True
        for item in list(res.async_items()):
            if OLD_CARD in str(item.get("url")):
                await res.async_delete_item(item["id"])
                _LOGGER.info("Removed the old card resource %s - the card now comes from the integration", item.get("url"))
    except Exception:  # noqa: BLE001 - the old resource just stays; the card guards against loading twice
        _LOGGER.debug("Could not tidy the old card resource", exc_info=True)


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
            async with self.session.get(f"{self.url}/api/control", timeout=aiohttp.ClientTimeout(total=10)) as r:
                data["control"] = await r.json() if r.status == 200 else {}
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
    await _card(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # An extra car added, removed, renamed or given its level in the app: its entities follow (a reload).
    seen = _cars_key(pilot.data)

    def _check() -> None:
        if pilot.last_update_success and _cars_key(pilot.data) != seen:
            hass.config_entries.async_schedule_reload(entry.entry_id)

    entry.async_on_unload(pilot.async_add_listener(_check))
    return True


def _cars_key(data: dict[str, Any] | None) -> list:
    return [(c.get("n"), c.get("name"), bool(c.get("soc_known"))) for c in (data or {}).get("cars") or []]


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

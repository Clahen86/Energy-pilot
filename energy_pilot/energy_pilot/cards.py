"""Dashboard cards: the card file is put where Home Assistant serves it (/local/), added to the dashboards'
resources, and fed by one sensor of Energy Pilot's own (sensor.energipilot) - the live numbers the card reads
straight from your own sensors, so it moves as fast as they do.

The sensor is Energy Pilot's own, so it is published in shadow too: it shows, it controls nothing.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
import shutil
from typing import Any

from .overview import Overview

_LOGGER = logging.getLogger(__name__)
SENSOR = "sensor.energipilot"
CARD = Path(__file__).parent / "frontend" / "energipilot-card.js"
HA_CONFIG = Path("/homeassistant")


class Cards:
    def __init__(self, ha: Any, overview: Overview, version: str) -> None:
        self.ha, self.overview, self.version = ha, overview, version
        self._last = ""

    async def run(self) -> None:
        await self.ha.connected.wait()
        await self.install()
        while True:
            try:
                await self.publish()
            except Exception:  # noqa: BLE001 - the cards wait for the next round
                _LOGGER.debug("Could not publish %s", SENSOR, exc_info=True)
            await asyncio.sleep(30)

    async def install(self) -> None:
        """Copy the card to /config/www/energipilot/ and add it to the dashboards' resources (UI dashboards)."""
        if not HA_CONFIG.is_dir():
            _LOGGER.info("Home Assistant's folder isn't mapped: add the card resource by hand")
            return
        target = HA_CONFIG / "www" / "energipilot" / CARD.name
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists() or target.read_bytes() != CARD.read_bytes():
                shutil.copyfile(CARD, target)
        except OSError:
            _LOGGER.warning("Could not copy the card to %s", target, exc_info=True)
            return
        stamp = hashlib.sha1(CARD.read_bytes()).hexdigest()[:8]
        url = f"/local/energipilot/{CARD.name}?v={stamp}"
        try:
            resources = await self.ha.command({"type": "lovelace/resources"})
        except Exception:  # noqa: BLE001 - YAML dashboards: the user adds it
            _LOGGER.info("Dashboards in YAML mode: add %s as a module resource", url)
            return
        mine = [r for r in resources if "/local/energipilot/" in str(r.get("url"))]
        if mine and mine[0]["url"] == url:
            return
        if mine:
            await self.ha.command({"type": "lovelace/resources/update", "resource_id": mine[0]["id"], "res_type": "module", "url": url})
        else:
            await self.ha.command({"type": "lovelace/resources/create", "res_type": "module", "url": url})
        _LOGGER.info("Card resource %s", url)

    async def publish(self) -> None:
        """sensor.energipilot: the decision as its state; the plan, prices and which sensors are which as attributes.
        Only written when something changed (not every minute), so it doesn't fill the database."""
        o = self.overview
        snap = o.snapshot(o.settings.get("language") or "da")
        decision = snap["decision"] or {}
        attrs = {
            "friendly_name": "Energipilot", "icon": "mdi:lightning-bolt-circle",
            # Several solar arrays: the card adds them up.
            "roles": {**o.roles(), **{k: v for k in ("pv_power",) if len(v := o.role_all(k)) > 1}}, "decision": decision, "plan": snap["plan"]["hours"],
            "price_min": snap["plan"]["price_min"], "price_max": snap["plan"]["price_max"], "cheapest": snap["plan"]["cheapest"],
            "battery_sign": o.battery_sign(),
            "solar": snap["solar"], "house_today": snap["house_today"], "ev": snap["ev"], "version": self.version,
        }
        key = json.dumps([decision.get("key"), decision.get("target"), attrs["plan"], attrs["ev"], attrs["roles"], attrs["solar"]],
                         sort_keys=True, default=str)
        if key == self._last and SENSOR in self.ha.states:
            return  # unchanged (after a Home Assistant restart the sensor is gone and is written again)
        await self.ha.set_state(SENSOR, decision.get("kind") or "unknown", attrs)
        self._last = key

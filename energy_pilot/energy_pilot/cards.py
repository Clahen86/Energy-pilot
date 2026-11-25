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


def _runtime(r: dict[str, Any] | None) -> dict[str, Any] | None:
    if not r:
        return None
    from datetime import datetime, timedelta

    def ten(iso: str | None) -> str | None:
        if not iso:
            return None
        t = datetime.fromisoformat(iso)
        t = t.replace(second=0, microsecond=0) - timedelta(minutes=t.minute % 10)
        return t.isoformat()
    return {"empty": bool(r.get("empty")), "until": ten(r.get("until")), "beyond": r.get("beyond") and ten(r["beyond"]), "low": r.get("low") and {"t": r["low"]["t"], "soc": round(r["low"]["soc"])},
            "full": r.get("full"), "cheap": r.get("cheap"), "storm": r.get("storm") and {k: r["storm"].get(k) for k in ("from", "to", "kind", "gust")}}


class Cards:
    def __init__(self, ha: Any, overview: Overview, version: str) -> None:
        self.ha, self.overview, self.version = ha, overview, version
        self._last = ""

    async def run(self) -> None:
        await self.ha.connected.wait()
        await self.install()
        n = 0
        while True:
            try:
                await self.publish()
                n += 1
                if n % 60 == 0:  # every half hour: the companion may have come from HACS since (it serves the card then)
                    await self.install()
            except Exception:  # noqa: BLE001 - the cards wait for the next round
                _LOGGER.debug("Could not publish %s", SENSOR, exc_info=True)
            await asyncio.sleep(30)

    async def install(self) -> None:
        """Copy the card to /config/www/energipilot/ and add it to the dashboards' resources (UI dashboards)."""
        if await self._integration_serves_card():
            await self._drop_old_resource()
            return  # the companion integration (1.0.0+) serves the card itself - nothing put into Home Assistant's folder
        if not HA_CONFIG.is_dir():
            _LOGGER.info("Home Assistant's folder isn't mapped: install the companion integration from HACS for the card")
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

    async def _integration_serves_card(self) -> bool:
        try:
            m = await self.ha.command({"type": "manifest/get", "integration": "energy_pilot"})
            entries = await self.ha.command({"type": "config_entries/get", "domain": "energy_pilot"})
        except Exception:  # noqa: BLE001 - not installed (or too old a Home Assistant)
            return False
        try:
            major = int(str((m or {}).get("version") or "0").split(".")[0])
        except ValueError:
            major = 0
        return major >= 1 and any(e.get("state") == "loaded" for e in entries or [])

    async def _drop_old_resource(self) -> None:
        try:
            resources = await self.ha.command({"type": "lovelace/resources"})
            for r in resources or []:
                if "/local/energipilot/" in str(r.get("url")):
                    await self.ha.command({"type": "lovelace/resources/delete", "resource_id": r["id"]})
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Could not drop the old card resource", exc_info=True)

    async def publish(self) -> None:
        """sensor.energipilot: the decision as its state; the plan, prices and which sensors are which as attributes.
        Only written when something changed (not every minute), so it doesn't fill the database."""
        o = self.overview
        snap = o.snapshot(str(o.settings.get("language") or o.ha.config.get("language") or "en")[:2])  # Home Assistant's own language
        decision = snap["decision"] or {}
        attrs = {
            "friendly_name": "Energy Pilot", "icon": "mdi:lightning-bolt-circle",
            # Several solar arrays: the card adds them up.
            "roles": {**o.roles(), **{k: v for k in ("pv_power", "other_power") if len(v := o.role_all(k)) > 1}}, "decision": decision, "plan": snap["plan"]["hours"],
            "price_min": snap["plan"]["price_min"], "price_max": snap["plan"]["price_max"], "cheapest": snap["plan"]["cheapest"],
            "battery_sign": o.battery_sign(),
            # how long the battery lasts (runtime.py) - to the nearest 10 minutes, so it isn't written every round
            "runtime": _runtime(snap.get("runtime")),
            "solar": snap["solar"], "house_today": snap["house_today"], "ev": snap["ev"], "version": self.version,
            # the card dresses its energy picture like the app: only what changes now and then (not the sun's height)
            "scene": {k: (round(v) if k == "outdoor" and isinstance(v, (int, float)) else v) for k, v in (snap.get("scene") or {}).items()
                      if k not in ("elevation", "cloud", "wind")} or None,
        }
        sc = attrs["scene"] or {}
        key = json.dumps([decision.get("key"), decision.get("target"), attrs["plan"], attrs["ev"], attrs["roles"], attrs["solar"], attrs["runtime"],
                          sc.get("time"), sc.get("condition"), sc.get("season"), (sc.get("holiday") or {}).get("key"),
                          sc.get("outdoor") is not None and sc["outdoor"] <= 0],
                         sort_keys=True, default=str)
        if key == self._last and SENSOR in self.ha.states:
            return  # unchanged (after a Home Assistant restart the sensor is gone and is written again)
        await self.ha.set_state(SENSOR, decision.get("kind") or "unknown", attrs)
        self._last = key
        self._write_uses(o)

    def _write_uses(self, o) -> None:
        """energy_pilot_uses.json in the app's folder: every sensor Energy Pilot reads (and learns from its history), so
        database tools like Database Doctor can see they're in use and never stop saving them."""
        try:
            ids = sorted({e for name in o.roles() for e in o.role_all(name) if e and "." in e})
            path = o.file.parent / "energy_pilot_uses.json"
            text = json.dumps({"app": "Energy Pilot", "history": True, "entities": ids}, indent=1)
            if not path.exists() or path.read_text() != text:
                path.write_text(text)
        except Exception:  # noqa: BLE001 - only a hint for other tools
            pass

"""Automatic updates: Home Assistant's own switch for this app, turned on from the panel when the user says yes.

Energy Pilot never updates itself - it only asks the Supervisor to turn on "Auto update" for this app (POST
/addons/self/options), the same switch as under Settings → Add-ons. Outside Home Assistant OS (Docker) there is none.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import aiohttp

_LOG = logging.getLogger(__name__)
_URL = "http://supervisor/addons/self"
_cache: dict[str, Any] = {"t": 0.0, "on": None}


def _headers() -> dict[str, str] | None:
    token = os.environ.get("SUPERVISOR_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else None


async def state() -> bool | None:
    """True/False when Home Assistant has the switch for this app, None when there is none. Asked at most every 10 min."""
    h = _headers()
    if not h:
        return None
    if time.time() - _cache["t"] < 600:
        return _cache["on"]
    try:
        async with aiohttp.ClientSession() as s, s.get(f"{_URL}/info", headers=h, timeout=aiohttp.ClientTimeout(total=10)) as r:
            data = (await r.json()).get("data") or {}
        _cache.update(t=time.time(), on=bool(data["auto_update"]) if "auto_update" in data else None)
    except Exception as err:  # noqa: BLE001 - no answer: no card
        _LOG.debug("auto update state: %s", err)
        _cache.update(t=time.time(), on=None)
    return _cache["on"]


async def turn_on() -> bool:
    h = _headers()
    if not h:
        return False
    try:
        async with aiohttp.ClientSession() as s, s.post(f"{_URL}/options", headers=h, json={"auto_update": True},
                                                        timeout=aiohttp.ClientTimeout(total=10)) as r:
            ok = r.status == 200
    except Exception as err:  # noqa: BLE001
        _LOG.warning("Could not turn on automatic updates: %s", err)
        return False
    _cache.update(t=time.time() if ok else 0.0, on=True if ok else None)
    if ok:
        _LOG.info("Automatic updates turned on for Energy Pilot (by the user)")
    return ok

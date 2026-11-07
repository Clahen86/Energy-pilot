"""The connection to Home Assistant: every state kept up to date, services, history.

Inside Home Assistant (as an app) it uses the Supervisor's token; in Docker a long-lived token and the address.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import logging
import os
from typing import Any, Callable

import aiohttp

_LOGGER = logging.getLogger(__name__)


def endpoints() -> tuple[str, str, str]:
    """(websocket url, rest url, token)."""
    if token := os.environ.get("SUPERVISOR_TOKEN"):
        return "ws://supervisor/core/websocket", "http://supervisor/core/api", token
    url = os.environ.get("HA_URL", "http://homeassistant.local:8123").rstrip("/")
    return url.replace("http", "ws", 1) + "/api/websocket", url + "/api", os.environ["HA_TOKEN"]


class HomeAssistant:
    def __init__(self) -> None:
        self.ws_url, self.rest_url, self.token = endpoints()
        self.states: dict[str, dict[str, Any]] = {}
        self.session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._event_handlers: dict[str, list[Callable[[dict[str, Any]], None]]] = {}
        self._subscribed: set[str] = set()
        self.on_state: list[Callable[[str, dict | None, dict | None], None]] = []
        self.connected = asyncio.Event()
        self.config: dict[str, Any] = {}

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    async def run(self) -> None:
        """Stay connected; reconnect after a Home Assistant restart."""
        self.session = aiohttp.ClientSession()
        while True:
            try:
                await self._connect()
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Lost Home Assistant (%s) - trying again in 10 s", err)
            self.connected.clear()
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("disconnected"))
            self._pending.clear()
            self._subscribed.clear()
            await asyncio.sleep(10)

    async def _connect(self) -> None:
        assert self.session is not None
        async with self.session.ws_connect(self.ws_url, heartbeat=30, max_msg_size=0) as ws:
            self._ws = ws
            await ws.receive_json()
            await ws.send_json({"type": "auth", "access_token": self.token})
            if (await ws.receive_json()).get("type") != "auth_ok":
                raise ConnectionError("Home Assistant refused the token")
            reader = asyncio.create_task(self._read(ws))
            try:
                self.config = await self.command({"type": "get_config"})
                states = await self.command({"type": "get_states"})
                self.states = {s["entity_id"]: s for s in states}
                await self._subscribe("state_changed")
                for event in list(self._event_handlers):
                    await self._subscribe(event)
                self.connected.set()
                _LOGGER.info("Connected to Home Assistant %s (%s entities)", self.config.get("version"), len(self.states))
                await reader
            finally:
                reader.cancel()

    async def _read(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            data = msg.json()
            for item in data if isinstance(data, list) else [data]:
                if item.get("type") == "event":
                    self._event(item["event"])
                elif (fut := self._pending.pop(item.get("id"), None)) and not fut.done():
                    if item.get("success", True):
                        fut.set_result(item.get("result"))
                    else:
                        fut.set_exception(RuntimeError(str(item.get("error"))))

    def _event(self, event: dict[str, Any]) -> None:
        kind = event.get("event_type")
        if kind == "state_changed":
            d = event["data"]
            new, old = d.get("new_state"), d.get("old_state")
            if new is None:
                self.states.pop(d["entity_id"], None)
            else:
                self.states[d["entity_id"]] = new
            for cb in self.on_state:
                cb(d["entity_id"], old, new)
        for cb in self._event_handlers.get(kind, []):
            cb(event)

    async def command(self, msg: dict[str, Any], timeout: float = 60) -> Any:
        if self._ws is None or self._ws.closed:
            raise ConnectionError("not connected")
        self._id += 1
        msg = {**msg, "id": self._id}
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[self._id] = fut
        await self._ws.send_json(msg)
        return await asyncio.wait_for(fut, timeout)

    async def _subscribe(self, event: str) -> None:
        if event in self._subscribed:
            return
        await self.command({"type": "subscribe_events", "event_type": event})
        self._subscribed.add(event)

    async def listen_event(self, event: str, cb: Callable[[dict[str, Any]], None]) -> None:
        self._event_handlers.setdefault(event, []).append(cb)
        if self.connected.is_set():
            await self._subscribe(event)

    async def call_service(self, domain: str, service: str, data: dict[str, Any], response: bool = False) -> Any:
        target = {k: data.pop(k) for k in ("entity_id", "device_id", "area_id") if k in data}
        msg: dict[str, Any] = {"type": "call_service", "domain": domain, "service": service, "service_data": data}
        if target:
            msg["target"] = target
        if response:
            msg["return_response"] = True
        return await self.command(msg, timeout=170)

    async def set_state(self, entity_id: str, state: Any, attributes: dict[str, Any] | None) -> None:
        assert self.session is not None
        async with self.session.post(f"{self.rest_url}/states/{entity_id}", headers=self.headers,
                                     json={"state": state, "attributes": attributes or {}}) as resp:
            resp.raise_for_status()

    async def history(self, entity_id: str, start: datetime, end: datetime | None) -> list[list[dict[str, Any]]]:
        assert self.session is not None
        params = {"filter_entity_id": entity_id}
        if end is not None:
            params["end_time"] = end.isoformat()
        async with self.session.get(f"{self.rest_url}/history/period/{start.isoformat()}", headers=self.headers,
                                    params=params, timeout=aiohttp.ClientTimeout(total=120)) as resp:
            resp.raise_for_status()
            return await resp.json()

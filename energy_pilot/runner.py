"""Runs the energy apps unchanged - in shadow (they only say what they would do) or in control.

Shadow means: no service is called and no state is written to Home Assistant. What the app would have done is kept,
and what it would have shown (its own sensors) is compared with what the running system shows, so you can see
whether the two agree before anything is switched over. The apps write their files (models, logs) in Energy Pilot's
own folder, never in AppDaemon's.
"""

from __future__ import annotations

import asyncio
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time as dtime, timedelta
import importlib.util
import json
import logging
import math
import os
from pathlib import Path
import re
import sys
import threading
import time
import traceback
import types
import uuid
from typing import Any, Callable
from zoneinfo import ZoneInfo

from . import hassapi
from .ha import HomeAssistant

_LOGGER = logging.getLogger(__name__)
SHADOW, CONTROL, OFF = "shadow", "control", "off"
CALL_TIMEOUT = 60


def install_shim() -> None:
    """`import appdaemon.plugins.hass.hassapi as hass` and `import hassapi as hass` both give our Hass."""
    for name in ("appdaemon", "appdaemon.plugins", "appdaemon.plugins.hass"):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["appdaemon.plugins.hass.hassapi"] = hassapi
    sys.modules["hassapi"] = hassapi
    sys.modules["appdaemon"].plugins = sys.modules["appdaemon.plugins"]  # type: ignore[attr-defined]
    sys.modules["appdaemon.plugins"].hass = sys.modules["appdaemon.plugins.hass"]  # type: ignore[attr-defined]
    sys.modules["appdaemon.plugins.hass"].hassapi = hassapi  # type: ignore[attr-defined]


class App:
    def __init__(self, name: str, module: str, cls: str, args: dict[str, Any]) -> None:
        self.name, self.module, self.cls, self.args = name, module, cls, args
        self.instance: hassapi.Hass | None = None
        self.thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix=name)
        self.log: deque = deque(maxlen=400)
        self.would: deque = deque(maxlen=300)  # services it would have called (shadow)
        self.errors = 0
        self.started: float | None = None
        self.shown: dict[str, dict[str, Any]] = {}  # entity -> what the app showed (its set_state)


class Runner:
    def __init__(self, ha: HomeAssistant, apps_dir: Path, data_dir: Path, apps: list[dict[str, Any]]) -> None:
        self.ha = ha
        self.apps_dir, self.data_dir = apps_dir, data_dir
        self.loop: asyncio.AbstractEventLoop | None = None
        self.apps: dict[str, App] = {a["name"]: App(a["name"], a["module"], a["class"], a.get("args") or {}) for a in apps}
        self.modes: dict[str, str] = {}
        self._handles: dict[str, Any] = {}
        self._state_listeners: dict[str, tuple[str, Callable, str | None, str | None, Any, Any, dict]] = {}
        self._overrides: dict[str, dict[str, Any]] = {}  # entities set by apps in shadow: what they see themselves
        self._lock = threading.RLock()
        self.compare: dict[str, dict[str, Any]] = {}
        self.tz = ZoneInfo("UTC")

    # ---------- modes ----------

    @property
    def _modes_file(self) -> Path:
        return self.data_dir / "energy_pilot_modes.json"

    def load_modes(self) -> None:
        try:
            self.modes = json.loads(self._modes_file.read_text())
        except (OSError, ValueError):
            self.modes = {}
        for name in self.apps:
            self.modes.setdefault(name, SHADOW)  # always starts in shadow

    def set_mode(self, name: str, mode: str) -> None:
        if name in self.apps and mode in (SHADOW, CONTROL, OFF):
            old = self.modes.get(name)
            self.modes[name] = mode
            self._modes_file.write_text(json.dumps(self.modes, indent=2))
            self.app_log(name, "INFO", f"Mode: {old} -> {mode}")
            if old == OFF and mode != OFF:
                self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._start_app(self.apps[name])))

    def all_to_shadow(self) -> None:
        for name in self.apps:
            if self.modes.get(name) == CONTROL:
                self.set_mode(name, SHADOW)

    def mode(self, name: str) -> str:
        return self.modes.get(name, SHADOW)

    # ---------- starting ----------

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        install_shim()
        self.load_modes()
        self.ha.on_state.append(self._on_state)
        await self.ha.connected.wait()
        self.tz = ZoneInfo(self.ha.config.get("time_zone") or "UTC")
        for app in self.apps.values():
            if self.mode(app.name) != OFF:
                await self._start_app(app)

    def _load_module(self, app: App) -> types.ModuleType:
        """The app's own file - with its "/config/..." paths pointed at Energy Pilot's folder."""
        path = self.apps_dir / f"{app.module}.py"
        source = path.read_text()
        data = str(self.data_dir).rstrip("/")
        source = re.sub(r"""(["'])/config/""", lambda m: f"{m[1]}{data}/", source)
        module = types.ModuleType(app.module)
        module.__file__ = str(path)
        sys.modules[app.module] = module
        exec(compile(source, str(path), "exec"), module.__dict__)  # noqa: S102 - the user's own app
        return module

    async def _start_app(self, app: App) -> None:
        def init() -> None:
            module = self._load_module(app)
            cls = getattr(module, app.cls)
            instance = cls.__new__(cls)
            hassapi.Hass.__init__(instance, self, app.name, app.args)
            app.instance = instance
            instance.initialize()

        try:
            await self.loop.run_in_executor(app.thread, init)
            app.started = time.time()
            self.app_log(app.name, "INFO", f"Started ({self.mode(app.name)})")
        except Exception:  # noqa: BLE001
            app.errors += 1
            self.app_log(app.name, "ERROR", "Could not start:\n" + traceback.format_exc())

    # ---------- logging ----------

    def app_log(self, name: str, level: str, text: str) -> None:
        app = self.apps.get(name)
        if app is not None:
            app.log.append({"t": time.time(), "level": level, "text": text[:4000]})
            if level in ("ERROR", "CRITICAL"):
                app.errors += 1
        logging.getLogger(f"app.{name}").log(getattr(logging, level, logging.INFO), text)

    # ---------- states (called from app threads) ----------

    def all_states(self, name: str) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {**self.ha.states, **self._overrides}

    def state_of(self, name: str, entity_id: str) -> dict[str, Any] | None:
        with self._lock:
            if entity_id in self._overrides:
                return self._overrides[entity_id]
        return self.ha.states.get(entity_id)

    def set_state(self, name: str, entity_id: str, state: Any, attributes: dict[str, Any] | None,
                  replace: bool) -> dict[str, Any]:
        app = self.apps[name]
        old = self.state_of(name, entity_id) or {}
        attrs = dict(attributes or {}) if replace else {**(old.get("attributes") or {}), **(attributes or {})}
        now = datetime.now(self.tz).isoformat()
        new = {"entity_id": entity_id, "state": str(state) if state is not None else old.get("state", "unknown"),
               "attributes": attrs, "last_changed": now if old.get("state") != state else old.get("last_changed", now),
               "last_updated": now}
        app.shown[entity_id] = new
        if self.mode(name) == CONTROL:
            self._sync(self.ha.set_state(entity_id, new["state"], attrs))
            with self._lock:
                self._overrides.pop(entity_id, None)
        else:
            with self._lock:
                self._overrides[entity_id] = new
            self._compare(name, entity_id)
        return new

    def call_service(self, name: str, service: str, data: dict[str, Any]) -> Any:
        domain, _, svc = service.replace(".", "/", 1).partition("/")
        if self.mode(name) != CONTROL:
            self.apps[name].would.append({"t": time.time(), "service": f"{domain}.{svc}", "data": _plain(data)})
            # What the app sets on a helper it sees itself, as if it had happened.
            self._pretend(domain, svc, data)
            return None
        return self._sync(self.ha.call_service(domain, svc, dict(data)))

    def _pretend(self, domain: str, svc: str, data: dict[str, Any]) -> None:
        entity = data.get("entity_id")
        if not isinstance(entity, str):
            return
        value = data.get("value", data.get("option"))
        if svc in ("set_value", "select_option") and value is not None:
            base = self.ha.states.get(entity) or {"entity_id": entity, "attributes": {}}
            with self._lock:
                self._overrides[entity] = {**base, "state": str(value)}

    def fire_event(self, name: str, event: str, data: dict[str, Any]) -> None:
        if self.mode(name) != CONTROL:
            self.apps[name].would.append({"t": time.time(), "service": f"event:{event}", "data": _plain(data)})
            return
        self._sync(self.ha.command({"type": "fire_event", "event_type": event, "event_data": data}))

    def history(self, entity_id: str, start: datetime, end: datetime | None) -> list[list[dict[str, Any]]]:
        if start.tzinfo is None:
            start = start.replace(tzinfo=self.tz)
        if end is not None and end.tzinfo is None:
            end = end.replace(tzinfo=self.tz)
        rows = self._sync(self.ha.history(entity_id, start, end), timeout=180) or []
        for group in rows:
            for row in group:
                for key in ("last_changed", "last_updated"):
                    if isinstance(row.get(key), str):
                        try:
                            row[key] = datetime.fromisoformat(row[key]).astimezone(self.tz)
                        except ValueError:
                            pass
        return rows

    def _sync(self, coro: Any, timeout: float = CALL_TIMEOUT) -> Any:
        """Run a coroutine on the loop from an app thread, and wait for it."""
        if threading.current_thread() is threading.main_thread():
            raise RuntimeError("called from the loop")
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    # ---------- comparing with the running system ----------

    def _compare(self, name: str, entity_id: str) -> None:
        """Shadow vs. the real entity (written by the system that runs now): same value?"""
        mine = self.apps[name].shown.get(entity_id)
        real = self.ha.states.get(entity_id)
        if mine is None or real is None:
            return
        c = self.compare.setdefault(entity_id, {"app": name, "checks": 0, "same": 0})
        c["checks"] += 1
        same = _same(mine.get("state"), real.get("state"))
        c["same"] += 1 if same else 0
        c.update(mine=mine.get("state"), real=real.get("state"), t=time.time(), last_same=same)

    # ---------- listening and timers ----------

    def _on_state(self, entity_id: str, old: dict | None, new: dict | None) -> None:
        for app in self.apps.values():
            if entity_id in app.shown and self.mode(app.name) != CONTROL:
                self._compare(app.name, entity_id)  # the running system just wrote its value: compare again
        for handle, (name, cb, ent, attribute, want_new, want_old, kwargs) in list(self._state_listeners.items()):
            if ent is not None and ent != entity_id:
                continue
            if self.mode(name) == OFF:
                continue
            if attribute is None:
                o, n = (old or {}).get("state"), (new or {}).get("state")
            elif attribute == "all":
                o, n = old, new
            else:
                o, n = ((old or {}).get("attributes") or {}).get(attribute), ((new or {}).get("attributes") or {}).get(attribute)
            if attribute != "all" and o == n:
                continue
            if want_new is not None and n != want_new:
                continue
            if want_old is not None and o != want_old:
                continue
            self._run(name, cb, entity_id, attribute or "state", o, n, dict(kwargs))

    def listen_state(self, name: str, cb: Callable, entity_id: str | None, attribute: str | None, new: Any, old: Any,
                     duration: float | None, kwargs: dict[str, Any]) -> str:
        handle = uuid.uuid4().hex
        self._state_listeners[handle] = (name, cb, entity_id, attribute, new, old, kwargs)
        return handle

    def listen_event(self, name: str, cb: Callable, event: str | None, kwargs: dict[str, Any]) -> str:
        handle = uuid.uuid4().hex
        filters = {k: v for k, v in kwargs.items() if k not in ("namespace",)}

        def on_event(e: dict[str, Any]) -> None:
            data = e.get("data") or {}
            if any(data.get(k) != v for k, v in filters.items()):
                return
            if handle in self._handles and self.mode(name) != OFF:
                self._run(name, cb, e.get("event_type"), data, dict(kwargs))

        self._handles[handle] = ("event", name)
        self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self.ha.listen_event(event or "*", on_event)))
        return handle

    def next_time(self, start: Any, daily: bool = False) -> float:
        """A timestamp for "now", a datetime (local, naive or aware), a time or "HH:MM:SS"."""
        now = datetime.now(self.tz)
        if start in (None, "now"):
            return now.timestamp()
        if isinstance(start, datetime):
            return (start if start.tzinfo else start.replace(tzinfo=self.tz)).timestamp()
        if isinstance(start, str):
            h, m, *s = (int(x) for x in start.split(":"))
            start = dtime(h, m, s[0] if s else 0)
        if isinstance(start, dtime):
            at = now.replace(hour=start.hour, minute=start.minute, second=start.second, microsecond=0)
            if at <= now:
                at += timedelta(days=1)
            return at.timestamp()
        raise ValueError(f"Unknown start time {start!r}")

    def schedule(self, name: str, cb: Callable, kwargs: dict[str, Any], delay: float | None = None,
                 at: float | None = None, every: float | None = None, daily: Any = None) -> str:
        handle = uuid.uuid4().hex
        when = time.time() + delay if delay is not None else at
        self._handles[handle] = ("timer", name)

        def arm(at_ts: float) -> None:
            if handle not in self._handles:
                return
            timer = self.loop.call_later(max(0.0, at_ts - time.time()), fire)
            self._handles[handle] = ("timer", name, timer)

        def fire() -> None:
            if handle not in self._handles:
                return
            if every:
                nxt = self.next_time(daily, daily=True) if daily is not None else time.time() + every
                arm(nxt)
            else:
                self._handles.pop(handle, None)
            if self.mode(name) != OFF:
                self._run(name, cb, dict(kwargs))

        self.loop.call_soon_threadsafe(arm, when)
        return handle

    def cancel(self, handle: str) -> bool:
        item = self._handles.pop(handle, None)
        self._state_listeners.pop(handle, None)
        if item and len(item) > 2:
            self.loop.call_soon_threadsafe(item[2].cancel)
        return item is not None

    def running(self, handle: str) -> bool:
        return handle in self._handles

    def _run(self, name: str, cb: Callable, *args: Any) -> None:
        app = self.apps[name]

        def call() -> None:
            try:
                cb(*args)
            except Exception:  # noqa: BLE001 - one failing callback doesn't stop the app
                self.app_log(name, "ERROR", f"{getattr(cb, '__name__', cb)} failed:\n" + traceback.format_exc())

        app.thread.submit(call)

    def stop(self) -> None:
        for app in self.apps.values():
            if app.instance is not None:
                try:
                    app.thread.submit(app.instance.terminate).result(10)
                except Exception:  # noqa: BLE001
                    pass
            app.thread.shutdown(wait=True, cancel_futures=True)
        for item in list(self._handles.values()):
            if len(item) > 2:
                item[2].cancel()
        self._handles.clear()

    # ---------- for the panel ----------

    def status(self) -> dict[str, Any]:
        out = []
        for app in self.apps.values():
            shown = sorted(app.shown)
            checks = [self.compare[e] for e in shown if e in self.compare]
            total = sum(c["checks"] for c in checks)
            same = sum(c["same"] for c in checks)
            out.append({
                "name": app.name, "mode": self.mode(app.name), "started": app.started, "errors": app.errors,
                "agree": round(100 * same / total) if total else None, "checks": total,
                "would": list(app.would)[-60:][::-1],
                "log": list(app.log)[-80:][::-1],
                "entities": [{"entity_id": e, **{k: v for k, v in self.compare.get(e, {}).items() if k != "app"},
                              "mine_now": app.shown[e].get("state")} for e in shown],
            })
        return {"apps": out, "connected": self.ha.connected.is_set(), "ha": self.ha.config.get("version")}


def _same(a: Any, b: Any) -> bool:
    try:
        x, y = float(a), float(b)
        return math.isclose(x, y, rel_tol=0.02, abs_tol=0.05)
    except (TypeError, ValueError):
        return str(a) == str(b)


def _plain(data: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in data.items():
        out[k] = v if isinstance(v, (str, int, float, bool, type(None), list, dict)) else str(v)
    return out

"""The part of AppDaemon's API the energy apps use - so they run here unchanged.

Every app runs in its own thread, like AppDaemon (callbacks of one app never run at the same time). Reading a state
is instant (all states are kept here); calling a service, setting a state and reading history go through the
runner, which in shadow mode only writes down what the app *would* have done.
"""

from __future__ import annotations

from datetime import datetime, time as dtime, timedelta
import logging
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from .runner import Runner


class Hass:
    def __init__(self, runner: Runner, name: str, args: dict[str, Any] | None = None) -> None:
        self._runner = runner
        self.name = name
        self.args = args or {}
        self.logger = logging.getLogger(f"app.{name}")

    # ---------- logging ----------

    def log(self, msg: Any, *args: Any, level: str = "INFO", **kwargs: Any) -> None:
        text = str(msg) % args if args else str(msg)
        self._runner.app_log(self.name, level.upper(), text)

    def error(self, msg: Any, *args: Any, level: str = "ERROR", **kwargs: Any) -> None:
        self.log(msg, *args, level=level)

    # ---------- time ----------

    def datetime(self, aware: bool = False) -> datetime:
        now = datetime.now(self._runner.tz)
        return now if aware else now.replace(tzinfo=None)

    def get_now(self) -> datetime:
        return datetime.now(self._runner.tz)

    def get_now_ts(self) -> float:
        return datetime.now(self._runner.tz).timestamp()

    def time(self) -> dtime:
        return self.datetime().time()

    def date(self):
        return self.datetime().date()

    # ---------- states ----------

    def get_state(self, entity_id: str | None = None, attribute: str | None = None, default: Any = None,
                  copy: bool = True, **kwargs: Any) -> Any:
        if entity_id is None:
            return {e: dict(s) for e, s in self._runner.all_states(self.name).items()}
        if "." not in entity_id:
            return {e: dict(s) for e, s in self._runner.all_states(self.name).items() if e.startswith(entity_id + ".")}
        s = self._runner.state_of(self.name, entity_id)
        if s is None:
            return default
        if attribute is None:
            return s.get("state", default)
        if attribute == "all":
            return {**s, "attributes": dict(s.get("attributes") or {})}
        return (s.get("attributes") or {}).get(attribute, default)

    def entity_exists(self, entity_id: str, **kwargs: Any) -> bool:
        return self._runner.state_of(self.name, entity_id) is not None

    def set_state(self, entity_id: str, state: Any = None, attributes: dict[str, Any] | None = None,
                  replace: bool = False, **kwargs: Any) -> dict[str, Any]:
        return self._runner.set_state(self.name, entity_id, state, attributes, replace)

    def call_service(self, service: str, **kwargs: Any) -> Any:
        kwargs.pop("namespace", None)
        return_result = kwargs.pop("return_result", False)
        kwargs.pop("callback", None)
        result = self._runner.call_service(self.name, service, kwargs)
        return result if return_result else result

    def turn_on(self, entity_id: str, **kwargs: Any) -> Any:
        return self.call_service("homeassistant/turn_on", entity_id=entity_id, **kwargs)

    def turn_off(self, entity_id: str, **kwargs: Any) -> Any:
        return self.call_service("homeassistant/turn_off", entity_id=entity_id, **kwargs)

    def fire_event(self, event: str, **kwargs: Any) -> None:
        self._runner.fire_event(self.name, event, kwargs)

    def get_history(self, entity_id: str | None = None, days: int | None = None, start_time: datetime | None = None,
                    end_time: datetime | None = None, **kwargs: Any) -> list[list[dict[str, Any]]]:
        entity_id = entity_id or kwargs.get("entity")
        if start_time is None:
            start_time = self.datetime(aware=True) - timedelta(days=days or 1)
        return self._runner.history(entity_id, start_time, end_time)

    # ---------- listening ----------

    def listen_state(self, callback: Callable, entity_id: str | None = None, attribute: str | None = None,
                     new: Any = None, old: Any = None, duration: float | None = None, **kwargs: Any) -> str:
        return self._runner.listen_state(self.name, callback, entity_id, attribute, new, old, duration, kwargs)

    def listen_event(self, callback: Callable, event: str | None = None, **kwargs: Any) -> str:
        return self._runner.listen_event(self.name, callback, event, kwargs)

    def cancel_listen_state(self, handle: str, **kwargs: Any) -> bool:
        return self._runner.cancel(handle)

    def cancel_listen_event(self, handle: str, **kwargs: Any) -> bool:
        return self._runner.cancel(handle)

    # ---------- timers ----------

    def run_in(self, callback: Callable, delay: float, **kwargs: Any) -> str:
        return self._runner.schedule(self.name, callback, delay=float(delay), kwargs=kwargs)

    def run_once(self, callback: Callable, start: Any, **kwargs: Any) -> str:
        return self._runner.schedule(self.name, callback, at=self._runner.next_time(start), kwargs=kwargs)

    def run_at(self, callback: Callable, start: Any, **kwargs: Any) -> str:
        return self.run_once(callback, start, **kwargs)

    def run_every(self, callback: Callable, start: Any, interval: float, **kwargs: Any) -> str:
        return self._runner.schedule(self.name, callback, at=self._runner.next_time(start), every=float(interval),
                                     kwargs=kwargs)

    def run_minutely(self, callback: Callable, start: Any = None, **kwargs: Any) -> str:
        return self.run_every(callback, start or "now", 60, **kwargs)

    def run_hourly(self, callback: Callable, start: Any = None, **kwargs: Any) -> str:
        return self.run_every(callback, start or "now", 3600, **kwargs)

    def run_daily(self, callback: Callable, start: Any, **kwargs: Any) -> str:
        return self._runner.schedule(self.name, callback, at=self._runner.next_time(start, daily=True),
                                     every=86400.0, daily=start, kwargs=kwargs)

    def cancel_timer(self, handle: str, **kwargs: Any) -> bool:
        return self._runner.cancel(handle)

    def timer_running(self, handle: str) -> bool:
        return self._runner.running(handle)

    # ---------- what AppDaemon apps sometimes override ----------

    def initialize(self) -> None:  # noqa: D401 - the app's own
        """Set up by the app."""

    def terminate(self) -> None:
        """Clean up by the app."""

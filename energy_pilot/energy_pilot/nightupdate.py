"""Updating at night: a new version is installed in the first quiet moment between midnight and six - never while the
battery charges from the grid or sells, never while the car charges - and only once it has been out a day (a bad
version is mended before most homes get it). On by default; "Update at night" in the settings turns it off.

Energy Pilot can't update itself through the Supervisor (an app's own token may not), so it asks Home Assistant to
install the update for this app (update.install on the app's update entity), as the user would from Settings.
Home Assistant's own "Auto update" switch for the app, when on, updates at once by itself - then this stays out.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
import os
import re
from typing import Any

_LOG = logging.getLogger(__name__)
NIGHT = (0, 6)  # from midnight to six
AGE_H = 24  # a version is installed only once it has been out this long
BUSY = {"charge_grid", "export"}  # the plan charging from the grid or selling: not a moment to restart
QUIET_MIN = 20  # the plan must be quiet this long from now
VERSION = re.compile(r"^\d+\.\d+\.\d+$")


def possible() -> bool:
    """Only under Home Assistant OS / Supervised (an app with a Supervisor token)."""
    return bool(os.environ.get("SUPERVISOR_TOKEN"))


def _v(text: str | None) -> tuple[int, ...] | None:
    return tuple(int(x) for x in str(text).split(".")) if text and VERSION.match(str(text)) else None


def quiet(steps: list[dict[str, Any]], now: datetime, minutes: int = QUIET_MIN) -> bool:
    """No grid charging or selling in the plan from now and the next minutes (the slot running now included)."""
    end = now + timedelta(minutes=minutes)
    slots = []
    for s in steps or []:
        try:
            slots.append((datetime.fromisoformat(s["t"]), s.get("action")))
        except (KeyError, TypeError, ValueError):
            continue
    slots.sort(key=lambda x: x[0])
    for i, (t, action) in enumerate(slots):
        nxt = slots[i + 1][0] if i + 1 < len(slots) else t + timedelta(minutes=60)
        if nxt > now and t < end and action in BUSY:
            return False
    return True


def due(now: datetime, installed: str | None, latest: str | None, seen_t: float | None, steps: list[dict[str, Any]],
        ev_w: float = 0.0, enabled: bool = True, ha_auto: bool | None = None) -> bool:
    """Is now the moment to install the waiting version?"""
    if not enabled or ha_auto:
        return False
    a, b = _v(installed), _v(latest)
    if a is None or b is None or b <= a:
        return False  # nothing newer - or a developer's own build ("dev", "0.1-test"): left alone
    if not NIGHT[0] <= now.hour < NIGHT[1]:
        return False
    if seen_t is None or now.timestamp() - seen_t < AGE_H * 3600:
        return False
    if ev_w > 100:
        return False  # the car charging: its session isn't cut by a restart
    return quiet(steps, now)


class NightUpdate:
    def __init__(self, overview: Any, ha: Any) -> None:
        self.ov, self.ha = overview, ha
        self._sent: str | None = None  # the version asked for (once per version and run)

    def entity(self) -> str | None:
        """The app's update entity: Home Assistant's Supervisor integration makes one per app (unique id <slug>_…)."""
        reg = getattr(getattr(self.ov, "controller", None), "_ent_reg", None) or {}
        slug = (os.environ.get("HOSTNAME") or "").replace("-", "_")
        found = [e for e, r in reg.items() if e.startswith("update.") and r.get("platform") == "hassio"
                 and ((slug and str(r.get("unique_id") or "").startswith(slug)) or "energy_pilot" in e)]
        return found[0] if found else None

    async def tick(self, now: datetime) -> None:
        if not possible():
            return
        e = self.entity()
        st = (self.ha.states.get(e) or {}) if e else {}
        a = st.get("attributes") or {}
        installed, latest = a.get("installed_version"), a.get("latest_version")
        if not latest:
            return
        seen = self.ov.settings.get("night_update_seen") or {}
        if seen.get("v") != latest:
            seen = {"v": latest, "t": now.timestamp()}
            self.ov.save({"night_update_seen": seen})  # when this version was first seen: its day starts now
        if self._sent == latest:
            return
        from . import autoupdate

        res = ((getattr(getattr(self.ov, "engine", None), "result", None) or {}).get("battery") or {})
        flow = self.ov.flow() if callable(getattr(self.ov, "flow", None)) else {}
        if not due(now, installed, latest, seen.get("t"), res.get("steps") or [], float((flow or {}).get("ev") or 0.0),
                   bool(self.ov.settings.get("night_update", True)), await autoupdate.state()):
            return
        self._sent = latest
        _LOG.info("Updating to %s now, in a quiet moment of the night", latest)
        try:
            await self.ha.call_service("update", "install", {"entity_id": e})
        except Exception:  # noqa: BLE001 - the restart itself may cut the answer; tried again next night if it didn't take
            _LOG.debug("update.install", exc_info=True)

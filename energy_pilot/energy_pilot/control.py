"""The engine's hands: turning the plan into what the inverter and the charger are told - in shadow first.

Every few minutes: what the plan wants now (battery: normal / hold / charge; car: charge / stop) is turned into
service calls through the adapter. In shadow they are only written down ("would do"); in control they are sent -
only when the intent changes, and again every half hour in case something else changed it. After sending, the
controls are read back to see that they took.

Safety:
- Starts in shadow, one part at a time.
- Won't take the battery while another system plans it (your AppDaemon), unless you say so.
- "Everything back to shadow" puts the battery back to normal before letting go.
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timedelta
import logging
import time
from typing import Any
from zoneinfo import ZoneInfo

from . import adapters

_LOGGER = logging.getLogger(__name__)
REASSERT_S = 1800


class Controller:
    def __init__(self, ha: Any, overview: Any, engine: Any) -> None:
        self.ha, self.ov, self.engine = ha, overview, engine
        self.entities: dict[str, list[str]] = {"battery": [], "car": []}
        self.platforms: dict[str, str | None] = {"battery": None, "car": None}
        self.last: dict[str, dict[str, Any]] = {}
        self.log: dict[str, deque] = {"battery": deque(maxlen=60), "car": deque(maxlen=60)}

    # ---------- settings ----------

    def mode(self, part: str) -> str:
        return ((self.ov.settings.get("control") or {}).get(part)) or "shadow"

    def set_mode(self, part: str, mode: str) -> None:
        modes = dict(self.ov.settings.get("control") or {})
        modes[part] = mode
        self.ov.save({"control": modes})
        self.last.pop(part, None)  # act again at once

    def blocked(self, part: str) -> str | None:
        """Why the engine may not control this part (None: it may)."""
        if part == "battery" and self.ov.role("battery_plan") and not self.ov.settings.get("battery_takeover"):
            return "other_system"  # another system plans the battery: never two at once
        if part == "battery" and not self.profile_steps():
            return "no_profile"
        if part == "car" and not self.entities["car"] and self.platforms["car"] not in adapters.CHARGER_SERVICES:
            return "no_charger"
        return None

    # ---------- what the controls are ----------

    async def discover(self) -> None:
        """The inverter's and the charger's controls: select/number/switch/button entities on the same device."""
        try:
            entities = await self.ha.command({"type": "config/entity_registry/list"})
        except Exception:  # noqa: BLE001
            return
        by_id = {e["entity_id"]: e for e in entities}
        for part, role in (("battery", "battery_soc"), ("car", "ev_power")):
            anchor = self.ov.role(role) or (self.ov.role("ev_plug") if part == "car" else None)
            dev = (by_id.get(anchor) or {}).get("device_id")
            plat = (by_id.get(anchor) or {}).get("platform")
            found = [e["entity_id"] for e in entities if not e.get("disabled_by") and e["entity_id"].split(".")[0] in ("select", "number", "switch", "button")
                     and ((dev and e.get("device_id") == dev) or (plat and e.get("platform") == plat and plat not in ("mqtt", "template")))]
            if not found and anchor:  # MQTT inverters: same name prefix
                prefix = anchor.split(".", 1)[1].split("_")[0]
                found = [e for e in self.ha.states if e.split(".")[0] in ("select", "number", "switch") and e.split(".", 1)[1].startswith(prefix + "_")]
            self.entities[part], self.platforms[part] = sorted(found), plat

    def profile_key(self) -> str | None:
        chosen = self.ov.settings.get("inverter_profile")
        if chosen:
            return chosen
        return adapters.guess_profile(self.entities["battery"], {self.platforms["battery"] or ""})

    def profile_steps(self) -> dict[str, list] | None:
        key = self.profile_key()
        if key == "custom":
            c = self.ov.settings.get("custom_profile") or {}
            steps = {i: [(s["entity"], s["kind"], s.get("value")) for s in c.get(i, []) if s.get("entity")] for i in ("normal", "hold", "charge")}
            return steps if any(steps.values()) else None
        p = adapters.PROFILES.get(key or "")
        return {i: p[i] for i in ("normal", "hold", "charge")} if p else None

    # ---------- deciding and acting ----------

    def intents(self) -> dict[str, dict[str, Any]]:
        res = (self.engine.result or {}) if self.engine else {}
        out: dict[str, dict[str, Any]] = {}
        f = self.ov.flow()
        b = res.get("battery")
        if b and b.get("steps"):
            step = b["steps"][0]
            bat = self.engine.settings()
            intent = {"charge_grid": "charge", "hold": "hold"}.get(step["action"], "normal")
            charge_kw = min(bat.max_charge_kw, max(0.5, (step["soc"] - (f["soc"] or 0)) / 100 * bat.capacity_kwh))
            out["battery"] = {"intent": intent, "ctx": {
                "min_soc": round(bat.min_soc), "soc": round(f["soc"] or bat.min_soc), "target": round(step["soc"]),
                "rate": round(100 * charge_kw / bat.max_charge_kw), "power_w": round(charge_kw * 1000),
                "max_power_w": round(bat.max_discharge_kw * 1000)}}
        if self.ov.ev() is not None:
            tz = ZoneInfo(self.ha.config.get("time_zone") or "UTC")
            hour = datetime.now(tz).replace(minute=0, second=0, microsecond=0)
            planned = {datetime.fromisoformat(t) for t in ((res.get("car") or {}).get("hours") or [])}
            manual = bool(self.ov.settings.get("ev_now"))
            charge = f.get("plug") and (manual or hour in planned)
            kw = float(self.ov.settings.get("charger_kw") or 7.4)
            phases = int(self.ov.settings.get("charger_phases") or (3 if kw > 7.5 else 1))
            out["car"] = {"intent": "charge" if charge else "stop", "ctx": {"current": min(32, max(6, kw * 1000 / (230 * phases)))}}
        return out

    def calls(self, part: str, want: dict[str, Any]) -> list[dict[str, Any]]:
        if part == "battery":
            steps = self.profile_steps() or {}
            return adapters.resolve(steps.get(want["intent"], []), self.entities["battery"], want["ctx"])
        return adapters.charger_calls(want["intent"], self.entities["car"], self.platforms["car"], want["ctx"]["current"])

    async def tick(self) -> None:
        for part, want in self.intents().items():
            mode = self.mode(part)
            if mode == "off":
                continue
            calls = self.calls(part, want)
            prev = self.last.get(part)
            changed = prev is None or prev["intent"] != want["intent"] or prev["ctx"] != want["ctx"]
            due = prev is None or time.time() - prev["t"] > REASSERT_S
            if not (changed or due):
                continue
            entry = {"t": time.time(), "intent": want["intent"], "ctx": want["ctx"], "calls": calls, "mode": mode}
            if mode == "control" and not self.blocked(part):
                entry["result"] = await self._send(calls)
            elif mode == "control":
                entry["blocked"] = self.blocked(part)
            self.last[part] = entry
            if changed:
                self.log[part].appendleft(entry)

    async def _send(self, calls: list[dict[str, Any]]) -> str:
        for c in calls:
            try:
                await self.ha.call_service(c["domain"], c["service"], dict(c["data"]))
                await asyncio.sleep(1.5)  # inverters take one change at a time
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Control call %s.%s failed: %s", c["domain"], c["service"], err)
                return f"failed: {c['domain']}.{c['service']}"
        await asyncio.sleep(15)
        return "ok" if self._took(calls) else "not_confirmed"

    def _took(self, calls: list[dict[str, Any]]) -> bool:
        """Did the controls take the values? (Selects and numbers that can be read back.)"""
        for c in calls:
            data = c["data"]
            e = data.get("entity_id")
            if not e or e not in self.ha.states:
                continue
            state = self.ha.states[e].get("state")
            want = data.get("option", data.get("value"))
            if want is None:
                continue
            try:
                if abs(float(state) - float(want)) > 0.6:
                    return False
            except (TypeError, ValueError):
                if str(state) != str(want):
                    return False
        return True

    async def release(self) -> None:
        """Back to shadow: the battery is put back to normal first, the charger is left as it is."""
        if self.mode("battery") == "control" and not self.blocked("battery"):
            want = self.intents().get("battery")
            if want:
                await self._send(self.calls("battery", {**want, "intent": "normal"}))
        modes = {p: "shadow" for p in ("battery", "car")}
        self.ov.save({"control": modes})
        self.last.clear()

    def status(self) -> dict[str, Any]:
        wants = self.intents()
        out = {}
        for part in ("battery", "car"):
            want = wants.get(part)
            out[part] = {
                "mode": self.mode(part), "blocked": self.blocked(part), "now": want,
                "calls": self.calls(part, want) if want else [], "log": list(self.log[part])[:20],
                "entities": self.entities[part],
            }
        key = self.profile_key()
        out["profile"] = {"key": key, "name": (adapters.PROFILES.get(key or "") or {}).get("name") or ("custom" if key == "custom" else None),
                          "choices": {k: p["name"] for k, p in adapters.PROFILES.items()}}
        return out

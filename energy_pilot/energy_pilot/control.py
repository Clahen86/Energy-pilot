"""The engine's hands: turning the plan into what the inverter and the charger are told - in shadow first.

Every few minutes: what the plan wants now (battery: normal / hold / charge; car: charge / stop) is turned into
service calls through the adapter. In shadow they are only written down ("would do"); in control they are sent -
only when the intent changes, and again every half hour in case something else changed it. After sending, the
controls are read back to see that they took.

Safety:
- Starts in shadow, one part at a time.
- Won't take the battery while another system plans it (your AppDaemon), unless you say so.
- "Everything back to shadow" puts the battery back to normal before letting go.
- Won't control if a control the profile needs is missing (another model, renamed, disabled) - never half a command.
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
        self.model: str | None = None
        self.services: set[str] | None = None
        self.last: dict[str, dict[str, Any]] = {}
        self.log: dict[str, deque] = {"battery": deque(maxlen=60), "car": deque(maxlen=60), "generator": deque(maxlen=60)}
        self._sun_on = False  # the car is charging on the sun's surplus (for the start/stop margin)
        self.car_why = ""

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
        if part == "battery" and __import__("energy_pilot.batteries", fromlist=["extras"]).extras(self.ov.settings):
            return "multi_battery"  # more than one battery: shadow only until sharing the work is tested
        if part == "battery" and not self.profile_steps():
            return "no_profile"
        if part == "battery" and adapters.missing(self.check()):
            return "missing_controls"
        if part == "battery" and self.ov.settings.get("offgrid"):
            return "offgrid"  # no grid to charge from: the inverter runs the battery, the engine runs the generator
        if part == "generator" and not self.ov.role("generator_switch"):
            return "no_generator"
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
        try:
            devices = {d["id"]: d for d in await self.ha.command({"type": "config/device_registry/list"})}
            dev = devices.get((by_id.get(self.ov.role("battery_soc") or "") or {}).get("device_id") or "") or {}
            parts = [x for x in (dev.get("model"), dev.get("model_id"), dev.get("name")) if x]
            self.model = " ".join(dict.fromkeys(parts)) or None  # "Growatt SPH", not "Growatt SPH Growatt SPH"
        except Exception:  # noqa: BLE001
            self.model = None
        try:
            svc = await self.ha.command({"type": "get_services"})
            self.services = {f"{d}.{n}" for d, names in svc.items() for n in names}
        except Exception:  # noqa: BLE001
            self.services = None
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
            if part == "car":
                self.car_device = dev  # Easee's actions want the charger's device
            if part == "battery":
                self.battery_device = dev  # for services that want the device (Huawei, GivEnergy)
                d = (devices or {}).get(dev or "") if "devices" in dir() else None
                self.battery_serial = (d or {}).get("serial_number") or ""  # Alpha ESS wants the serial

    def profile_key(self) -> str | None:
        chosen = self.ov.settings.get("inverter_profile")
        if chosen:
            return chosen
        return adapters.guess_profile(self.entities["battery"], {self.platforms["battery"] or ""}, self.model)

    def profile_steps(self) -> dict[str, list] | None:
        key = self.profile_key()
        if key == "custom":
            c = self.ov.settings.get("custom_profile") or {}
            steps = {i: [(s["entity"], s["kind"], s.get("value")) for s in c.get(i, []) if s.get("entity")] for i in ("normal", "hold", "charge")}
            return steps if any(steps.values()) else None
        p = adapters.PROFILES.get(key or "")
        return {i: p[i] for i in ("normal", "hold", "charge")} if p else None

    def check(self) -> dict[str, dict]:
        """Which of the profile's controls were found on the inverter, and which are missing."""
        steps = self.profile_steps() or {}
        key = self.profile_key()
        optional = (adapters.PROFILES.get(key or "") or {}).get("optional") or []
        return adapters.check(steps, self._pool(), optional, self.services) if steps else {}

    def _pool(self) -> list[str]:
        """Built-in profiles look only at the inverter's own controls; a custom one may pick any entity."""
        return self.entities["battery"] + (list(self.ha.states) if self.profile_key() == "custom" else [])

    # ---------- deciding and acting ----------

    def intents(self) -> dict[str, dict[str, Any]]:
        res = (self.engine.result or {}) if self.engine else {}
        out: dict[str, dict[str, Any]] = {}
        f = self.ov.flow()
        b = res.get("battery")
        if b and b.get("steps"):
            step = b["steps"][0]
            bat = self.engine.settings()
            intent = {"charge_grid": "charge", "hold": "hold", "export": "export"}.get(step["action"], "normal")
            slot_h = (b.get("slot_min") or 60) / 60  # the step is one price slot (a quarter of an hour in Europe)
            charge_kw = min(bat.max_charge_kw, max(0.5, (step["soc"] - (f["soc"] or 0)) / 100 * bat.capacity_kwh / slot_h))
            export_w = 0
            if intent == "export":  # the battery's discharge power: the house's share and what is sold
                charge_kw = min(bat.max_discharge_kw, max(0.5, ((f["soc"] or 0) - step["soc"]) / 100 * bat.capacity_kwh / slot_h))
                export_w = int(round(max(0.0, -(step.get("grid") or 0.0)) / slot_h * 1000 / 50) * 50)
            out["battery"] = {"intent": intent, "ctx": {
                "min_soc": round(bat.min_soc), "soc": round(f["soc"] or bat.min_soc), "target": round(b.get("target") or step["soc"]),
                "rate": round(100 * charge_kw / bat.max_charge_kw), "power_w": round(charge_kw * 1000),
                "max_power_w": round(bat.max_discharge_kw * 1000), "max_charge_w": round(bat.max_charge_kw * 1000),
                "power_kw": round(charge_kw, 2), "max_charge_kw": round(bat.max_charge_kw, 2), "max_power_kw": round(bat.max_discharge_kw, 2), "export_w": export_w,
                "device_id": getattr(self, "battery_device", None) or "", "serial": getattr(self, "battery_serial", "") or ""}}
            if "{house_w}" in str(self.profile_steps() or {}):
                # Only for profiles that use it (EcoFlow), rounded - so others aren't re-sent at every small change.
                out["battery"]["ctx"]["house_w"] = int(round((f.get("house") or 0.0) / 50) * 50)
        g = res.get("generator")
        if g and self.ov.settings.get("offgrid"):
            out["generator"] = {"intent": "run" if g.get("run") else "off", "ctx": {"why": g.get("why")}}
        if self.ov.ev() is not None:
            tz = ZoneInfo(self.ha.config.get("time_zone") or "UTC")
            car = res.get("car") or {}
            now = datetime.now(tz)
            slot = int(car.get("slot_min") or 60)
            hour = now.replace(minute=now.minute // slot * slot if slot < 60 else 0, second=0, microsecond=0)  # the slot now
            planned = {datetime.fromisoformat(t) for t in (car.get("hours") or [])}
            manual = bool(self.ov.settings.get("ev_now"))
            from .carspeed import decide

            st = dict(self.ov.settings)
            if st.get("ev_follow_sun") is None:
                st["ev_follow_sun"] = bool(self.ov.role("pv_power"))  # on by default when there is solar
            need = float(car.get("need_kwh") if car.get("need_kwh") is not None else 1.0)
            d = decide(f, st, hour in planned, manual, need, self._sun_on)
            self._sun_on, self.car_why = d["sun"], d["why"]
            out["car"] = {"intent": "charge" if d["charge"] else "stop", "ctx": {"current": d["current"]}}
        return out

    def calls(self, part: str, want: dict[str, Any]) -> list[dict[str, Any]]:
        if part == "generator":
            e = self.ov.role("generator_switch")
            if not e:
                return []
            return [{"domain": e.split(".")[0], "service": "turn_on" if want["intent"] == "run" else "turn_off", "data": {"entity_id": e}}]
        if part == "battery":
            steps = self.profile_steps() or {}
            # A profile without a way to sell runs normally instead (the plan doesn't sell then anyway).
            return self._clamp(adapters.resolve(steps.get(want["intent"]) or steps.get("normal", []), self._pool(), want["ctx"]))
        return self._clamp(adapters.charger_calls(want["intent"], self.entities["car"], self.platforms["car"], want["ctx"]["current"],
                                                  getattr(self, "car_device", None)))

    def _clamp(self, calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Numbers within the control's own min/max - Home Assistant refuses a value outside them."""
        for c in calls:
            d = c["data"]
            if c.get("service") == "set_value" and isinstance(d.get("value"), (int, float)):
                a = (self.ha.states.get(d.get("entity_id")) or {}).get("attributes") or {}
                try:
                    lo, hi = float(a.get("min", "-inf")), float(a.get("max", "inf"))
                except (TypeError, ValueError):
                    continue
                v = min(hi, max(lo, d["value"]))
                d["value"] = int(v) if float(v).is_integer() else v
        return calls

    async def tick(self, parts: tuple[str, ...] = ("battery", "car", "generator")) -> None:
        for part, want in self.intents().items():
            if part not in parts:
                continue
            mode = self.mode(part)
            if mode == "off":
                continue
            calls = self.calls(part, want)
            prev = self.last.get(part)
            changed = prev is None or prev["intent"] != want["intent"] or prev["ctx"] != want["ctx"]
            again = (adapters.PROFILES.get(self.profile_key() or "") or {}).get("reassert_s", REASSERT_S) if part == "battery" else REASSERT_S
            due = prev is None or time.time() - prev["t"] > again  # Solis' remote control times out after 30 min
            if not (changed or due):
                continue
            entry = {"t": time.time(), "intent": want["intent"], "ctx": want["ctx"], "calls": calls, "mode": mode}
            if mode == "control" and not self.blocked(part):
                calls = calls + self._restore(part, want["intent"])
                entry["calls"] = calls
                entry["result"] = await self._send(calls)
                if entry["result"] == "ok" and want["intent"] != "export" and part == "battery":
                    self.ov.save({"restore_values": {}})  # the owner's settings are back
            elif mode == "control":
                entry["blocked"] = self.blocked(part)
            self.last[part] = entry
            if changed:
                self.log[part].appendleft(entry)

    def _restore(self, part: str, intent: str) -> list[dict[str, Any]]:
        """Settings that are the owner's own (Victron's grid setpoint, Deye's work mode): remembered before selling,
        put back when selling stops - kept on disk, so a restart in between doesn't lose them."""
        pats = (adapters.PROFILES.get(self.profile_key() or "") or {}).get("restore") or []
        if part != "battery" or not pats:
            return []
        saved = dict(self.ov.settings.get("restore_values") or {})
        if intent == "export":
            if not saved:
                pool = self._pool()
                for p in pats:
                    e = adapters._find(p, pool)
                    st = (self.ha.states.get(e) or {}).get("state") if e else None
                    if e and st not in (None, "unknown", "unavailable"):
                        saved[e] = st
                if saved:
                    self.ov.save({"restore_values": saved})
            return []
        out = []
        for e, v in saved.items():
            if e.startswith("select."):
                out.append({"domain": "select", "service": "select_option", "data": {"entity_id": e, "option": v}})
            else:
                try:
                    num = float(v)
                except ValueError:
                    continue
                out.append({"domain": e.split(".")[0], "service": "set_value", "data": {"entity_id": e, "value": int(num) if num.is_integer() else num}})
        return out

    async def _send(self, calls: list[dict[str, Any]]) -> str:
        """Send the calls - only those whose value isn't already set (some links, like Solarman, drop writes now
        and then, so fewer writes is safer). A value that didn't stick is sent once more."""
        todo = [c for c in calls if not self._matches(c)]
        for attempt in range(2):
            for c in todo:
                try:
                    await self.ha.call_service(c["domain"], c["service"], dict(c["data"]))
                    await asyncio.sleep(1.5)  # inverters take one change at a time
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Control call %s.%s failed: %s", c["domain"], c["service"], err)
                    if attempt:
                        return f"failed: {c['domain']}.{c['service']}"
            if not todo:
                return "ok"
            await asyncio.sleep(15)
            todo = [c for c in calls if self._matches(c) is False]
            if not todo:
                return "ok"
            if not attempt:
                _LOGGER.info("Not taken, sending again: %s", ", ".join(c["data"].get("entity_id", "") for c in todo))
        return "not_confirmed"

    def _matches(self, c: dict[str, Any]) -> bool | None:
        """Has this control the wanted value already? None: it can't be read back (a switch, a service)."""
        data = c["data"]
        e, want = data.get("entity_id"), data.get("option", data.get("value"))
        if not isinstance(e, str) or want is None or e not in self.ha.states:
            return None
        state = self.ha.states[e].get("state")
        try:
            return abs(float(state) - float(want)) <= 0.6
        except (TypeError, ValueError):
            return str(state) == str(want)

    def _took(self, calls: list[dict[str, Any]]) -> bool:
        """Did the controls take the values? (Selects and numbers that can be read back.)"""
        return all(self._matches(c) is not False for c in calls)

    async def release(self) -> None:
        """Back to shadow: the battery is put back to normal first, the charger is left as it is."""
        if self.mode("battery") == "control" and not self.blocked("battery"):
            want = self.intents().get("battery")
            if want:
                await self._send(self.calls("battery", {**want, "intent": "normal"}))
        modes = {p: "shadow" for p in ("battery", "car", "generator")}
        self.ov.save({"control": modes})
        self.last.clear()

    def status(self) -> dict[str, Any]:
        wants = self.intents()
        out = {}
        for part in ("battery", "car", "generator"):
            want = wants.get(part)
            out[part] = {
                "mode": self.mode(part), "blocked": self.blocked(part), "now": want,
                "calls": self.calls(part, want) if want else [], "log": list(self.log[part])[:20],
                "entities": self.entities.get(part, []),
            }
        key = self.profile_key()
        prof = adapters.PROFILES.get(key or "") or {}
        out["profile"] = {"key": key, "name": prof.get("name") or ("custom" if key == "custom" else None),
                          "choices": {k: p["name"] for k, p in sorted(adapters.PROFILES.items(), key=lambda kv: kv[1]["name"].lower())},
                          "tested_keys": [k for k, p in adapters.PROFILES.items() if p.get("tested")],
                          "model": self.model, "tested": bool(prof.get("tested")) if key != "custom" else None, "check": self.check()}
        # For "Chosen by you": every control in Home Assistant - the inverter's own first - not only the device
        # the battery level was found on (that could be the wrong one, e.g. a car).
        own = set(self.entities["battery"])
        everything = [e for e in self.ha.states if e.split(".")[0] in ("select", "number", "switch", "button", "time")]
        out["profile"]["all_controls"] = sorted(own) + sorted(e for e in everything if e not in own)
        return out

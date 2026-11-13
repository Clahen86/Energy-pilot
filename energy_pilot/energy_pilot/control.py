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
import re
import time
from typing import Any
from zoneinfo import ZoneInfo

from . import adapters

# Platforms that hold anything (helpers, sums, MQTT): their entities never belong to one inverter or charger.
GENERIC_PLATFORMS = ("mqtt", "template", "group", "min_max", "integration", "utility_meter", "statistics", "filter",
                     "derivative", "threshold", "trend", "compensation", "powercalc", "sql", "rest", "command_line")

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
        self.car_devices: dict[str, str | None] = {}  # the extra chargers' devices (car2, car3 …)
        self.bat_info: dict[str, dict[str, Any]] = {}  # the extra batteries' inverter: device, model, serial
        self._sun_on_more: dict[str, bool] = {}
        self.more_why: dict[str, str] = {}
        self._sun_on = False  # the car is charging on the sun's surplus (for the start/stop margin)
        self.car_why = ""
        self.lone_ok: dict[str, bool] = {}  # a charger's only switch may start it (found on its own device)
        self.chosen: dict[str, str] = {}  # the switch picked for a charger in the settings
        self.switch_options: list[dict[str, Any]] = []
        self._devices: dict[str, dict[str, Any]] = {}
        self.discovered = False  # the controls looked up at least once since the start
        self.thing_candidates: list[dict[str, Any]] = []  # machines and small batteries worth offering (things.find)
        # Controls that went back to another value after they were set (Victron's defaults, Predbat, an automation):
        # part -> [(time, entity)], the last hour.
        self.drift: dict[str, list[tuple[float, str]]] = {}

    # ---------- settings ----------

    def car_parts(self) -> list[str]:
        """The extra chargers as parts of their own: car2, car3 … - each starts in shadow and is turned on by itself."""
        from . import chargers

        return [f"car{i + 2}" for i in range(len(chargers.extras(self.ov.settings)))]

    def bat_parts(self) -> list[str]:
        """The extra batteries (bat2, bat3 …): each talks to its own inverter, starts in shadow, turned on by itself."""
        from . import batteries

        return [f"bat{i + 2}" for i in range(len(batteries.extras(self.ov.settings)))]

    def parts(self) -> list[str]:
        return ["battery", *self.bat_parts(), "car", "generator", *self.car_parts()]

    @staticmethod
    def is_battery(part: str) -> bool:
        return part == "battery" or part.startswith("bat")

    def mode(self, part: str) -> str:
        return ((self.ov.settings.get("control") or {}).get(part)) or "shadow"

    async def hand_back(self, part: str) -> None:
        """A battery leaving control: normal again and the owner's own settings back (a grid setpoint left selling
        would go on selling in shadow)."""
        if self.mode(part) != "control" or not self.is_battery(part) or self.blocked(part):
            return
        want = self.intents().get(part)
        if want:
            await self._send(self.calls(part, {**want, "intent": "normal"}) + self._restore(part, "normal"))

    def set_mode(self, part: str, mode: str) -> None:
        modes = dict(self.ov.settings.get("control") or {})
        modes[part] = mode
        self.ov.save({"control": modes})
        self.last.pop(part, None)  # act again at once

    def blocked(self, part: str) -> str | None:
        """Why the engine may not control this part (None: it may)."""
        if self.is_battery(part) and self.ov.role("battery_plan") and not self.ov.settings.get("battery_takeover"):
            return "other_system"  # another system plans the battery: never two at once
        if self.is_battery(part) and not self.profile_steps(part):
            return "no_profile"
        if self.is_battery(part) and adapters.missing(self.check(part)):
            return "missing_controls"
        if self.is_battery(part) and self.ov.settings.get("offgrid"):
            return "offgrid"  # no grid to charge from: the inverter runs the battery, the engine runs the generator
        if part == "generator" and not self.ov.role("generator_switch"):
            return "no_generator"
        if part.startswith("car") and not self._can_drive(part):
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
        self.phones = {e["entity_id"] for e in entities if e.get("platform") == "mobile_app"}  # phones and tablets
        try:
            devices = {d["id"]: d for d in await self.ha.command({"type": "config/device_registry/list"})}
            self._devices = devices
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
            if part == "car":
                # The charger's own device: the power sensor's - or, when that is a sum/group/template of several
                # (no device), the plug's or the session's (a Zappi behind an "All EV power" group).
                for r in ("ev_power", "ev_plug", "ev_session"):
                    e = self.ov.role(r)
                    if e and (by_id.get(e) or {}).get("device_id"):
                        anchor = e
                        break
            dev = (by_id.get(anchor) or {}).get("device_id")
            plat = (by_id.get(anchor) or {}).get("platform")
            found = [e["entity_id"] for e in entities if not e.get("disabled_by") and e["entity_id"].split(".")[0] in ("select", "number", "switch", "button")
                     and ((dev and e.get("device_id") == dev) or (plat and e.get("platform") == plat and plat not in GENERIC_PLATFORMS
                                                                   and not (part == "car" and dev)))]
            # The charger: only its own device when it has one - Tuya, say, also has the air conditioner and the cat's
            # litter box, and their switches must never be taken for the charger's.
            if not found and anchor and part == "battery":  # MQTT inverters: same name prefix (never for a charger)
                prefix = anchor.split(".", 1)[1].split("_")[0]
                found = [e for e in self.ha.states if e.split(".")[0] in ("select", "number", "switch") and e.split(".", 1)[1].startswith(prefix + "_")]
            self.entities[part], self.platforms[part] = sorted(found), plat
            if part == "car":
                self.car_device = dev  # Easee's actions want the charger's device
                self.lone_ok["car"] = bool(dev)
            if part == "battery":
                self.battery_device = dev  # for services that want the device (Huawei, GivEnergy)
                d = (devices or {}).get(dev or "") if "devices" in dir() else None
                self.battery_serial = (d or {}).get("serial_number") or ""  # Alpha ESS wants the serial

        # The extra chargers: the controls on the device of their power (or plug) sensor.
        from . import chargers

        for part, c in zip(self.car_parts(), chargers.extras(self.ov.settings)):
            anchor = c.get("power") or c.get("plug")
            dev = (by_id.get(anchor) or {}).get("device_id")
            plat = (by_id.get(anchor) or {}).get("platform")
            found = [e["entity_id"] for e in entities if not e.get("disabled_by") and dev and e.get("device_id") == dev
                     and e["entity_id"].split(".")[0] in ("select", "number", "switch", "button")]
            self.entities[part], self.platforms[part], self.car_devices[part] = sorted(found), plat, dev
            self.lone_ok[part] = bool(dev)

        # The switch chosen for a charger (Settings → Car → Control): it starts and stops the car, and a current
        # control on its device (Tuya Local, ESPHome …) sets the speed. Only charging switches are offered.
        skip = {d for d in [getattr(self, "battery_device", None)] if d}
        self._chosen_switches(entities, by_id, skip)
        try:
            from . import things as _things

            taken = {x for t in (self.ov.settings.get("things") or []) for x in (t.get("switch"), t.get("start"), t.get("power")) if x}
            taken |= {x for x in (self.ov.role("ev_power"), self.ov.role("battery_power"), self.ov.role("house_power")) if x}
            self.thing_candidates = _things.find(entities, self._devices, self.ha.states, taken,
                                                 list(self.ov.settings.get("things_dismissed") or []))
        except Exception:  # noqa: BLE001
            self.thing_candidates = []
        self.discovered = True

        # The extra batteries: the controls of the inverter their level sensor sits on.
        from . import batteries

        for part, bt in zip(self.bat_parts(), batteries.extras(self.ov.settings)):
            reg = by_id.get(bt.get("soc")) or {}
            dev, plat = reg.get("device_id"), reg.get("platform")
            found = [e["entity_id"] for e in entities if not e.get("disabled_by") and e["entity_id"].split(".")[0] in ("select", "number", "switch", "button")
                     and ((dev and e.get("device_id") == dev) or (plat and e.get("platform") == plat and plat not in ("mqtt", "template")
                                                                   and plat != self.platforms.get("battery")))]
            d = (devices or {}).get(dev or "") if "devices" in dir() else None
            model = " ".join(dict.fromkeys(x for x in ((d or {}).get("model"), (d or {}).get("model_id"), (d or {}).get("name")) if x)) or None
            self.entities[part], self.platforms[part] = sorted(found), plat
            self.bat_info[part] = {"device": dev or "", "model": model, "serial": (d or {}).get("serial_number") or ""}

    def _chosen_switches(self, entities: list[dict[str, Any]], by_id: dict[str, dict[str, Any]], skip: set[str]) -> None:
        from . import chargers

        more = chargers.extras(self.ov.settings)
        anchors = [self.ov.role("ev_power"), self.ov.role("ev_plug")] + [x for c in more for x in (c.get("power"), c.get("plug"))]
        for b in (self.ov.settings.get("batteries") or []):
            if isinstance(b, dict) and (d := (by_id.get(b.get("soc") or "") or {}).get("device_id")):
                skip.add(d)
        self.switch_options = chargers.switch_options(entities, self._devices, self.ha.states, [a for a in anchors if a], skip)
        chosen = {"car": self.ov.settings.get("ev_switch")} | {p: c.get("switch") for p, c in zip(self.car_parts(), more)}
        self.chosen = {}
        for part, sw in chosen.items():
            reg = by_id.get(sw or "")
            if not reg:
                continue
            dev = reg.get("device_id")
            own = [e["entity_id"] for e in entities if not e.get("disabled_by") and dev and e.get("device_id") == dev
                   and re.match(r"(number|select)\.", e["entity_id"])]
            self.entities[part] = sorted(set(own) | {sw})
            self.platforms[part], self.chosen[part] = None, sw  # the generic way: the switch and a current control
            if part == "car":
                self.car_device = dev
            else:
                self.car_devices[part] = dev

    def _can_drive(self, part: str) -> bool:
        """A charger can be run: by its integration's own actions, a switch, or a current control."""
        if self.platforms.get(part) in adapters.CHARGER_SERVICES:
            return True
        ents = self.entities.get(part) or []
        return bool(self.auto_switch(part)) or any(re.search(adapters.CHARGER_CURRENT, e) for e in ents)

    def onoff(self, part: str) -> bool:
        """A charger that can only be switched on and off (a Shelly, a smart plug): full power or nothing."""
        if getattr(self, "platforms", {}).get(part) in adapters.CHARGER_SERVICES:
            return False
        ents = getattr(self, "entities", {}).get(part) or []
        return bool(ents) and not any(re.search(adapters.CHARGER_CURRENT, e) or re.search(adapters.CHARGER_CURRENT_SELECT, e) for e in ents)

    def auto_switch(self, part: str) -> str | None:
        """The switch this charger is started and stopped with now - chosen, or found by itself."""
        ents = self.entities.get(part) or []
        return self.chosen.get(part) or adapters.charger_switch(ents, self.lone_ok.get(part, False))

    def _extra_battery(self, part: str) -> dict[str, Any]:
        from . import batteries

        more = batteries.extras(self.ov.settings)
        i = self.bat_parts().index(part) if part in self.bat_parts() else -1
        return more[i] if 0 <= i < len(more) else {}

    def profile_key(self, part: str = "battery") -> str | None:
        if part != "battery":
            chosen = self._extra_battery(part).get("profile")
            if chosen:
                return chosen
            info = self.bat_info.get(part) or {}
            return adapters.guess_profile(self.entities.get(part, []), {self.platforms.get(part) or ""}, info.get("model"))
        chosen = self.ov.settings.get("inverter_profile")
        if chosen:
            return chosen
        return adapters.guess_profile(self.entities["battery"], {self.platforms["battery"] or ""}, self.model)

    def profile_steps(self, part: str = "battery") -> dict[str, list] | None:
        key = self.profile_key(part)
        if key == "custom" and part == "battery":
            c = self.ov.settings.get("custom_profile") or {}
            steps = {i: [(s["entity"], s["kind"], s.get("value")) for s in c.get(i, []) if s.get("entity")] for i in ("normal", "hold", "charge")}
            return steps if any(steps.values()) else None
        p = adapters.PROFILES.get(key or "")
        return {i: p[i] for i in ("normal", "hold", "charge", "export") if i in p} if p else None

    def check(self, part: str = "battery") -> dict[str, dict]:
        """Which of the profile's controls were found on the inverter, and which are missing."""
        steps = self.profile_steps(part) or {}
        key = self.profile_key(part)
        optional = (adapters.PROFILES.get(key or "") or {}).get("optional") or []
        return adapters.check(steps, self._pool(part), optional, self.services) if steps else {}

    def _pool(self, part: str = "battery") -> list[str]:
        """Built-in profiles look only at the inverter's own controls; a custom one may pick any entity. A profile
        with distinctive names (Victron's ess_…) also finds its controls on another device."""
        own = self.entities.get(part, []) if part != "battery" else self.entities["battery"]
        key = self.profile_key(part)
        if part == "battery" and key == "custom":
            return own + list(self.ha.states)
        prof = adapters.PROFILES.get(key or "") or {}
        if prof.get("anywhere"):
            pats = [st[0] for i in ("normal", "hold", "charge", "export") for st in prof.get(i, []) if isinstance(st[0], str)]
            extra = [e for e in self.ha.states if e not in own and e.split(".")[0] in ("select", "number", "switch", "button")
                     and any(re.search(p, e) for p in pats)]
            return own + sorted(extra)
        return own

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
            # The time left of the slot: the battery is to reach the step's level by its end, so the power follows
            # what is really left - not the whole slot (that left the battery above the plan when the house used less).
            left_h = slot_h
            try:
                start = datetime.fromisoformat(step["t"])
                left_h = min(slot_h, max(5 / 60, slot_h - (datetime.now(start.tzinfo) - start).total_seconds() / 3600))
            except (KeyError, TypeError, ValueError):
                pass
            charge_kw = min(bat.max_charge_kw, max(0.5, (step["soc"] - (f["soc"] or 0)) / 100 * bat.capacity_kwh / left_h))
            export_w = 0
            if intent == "export":  # the battery's discharge power: the house's share and what is sold
                charge_kw = min(bat.max_discharge_kw, max(0.5, ((f["soc"] or 0) - step["soc"]) / 100 * bat.capacity_kwh / left_h))
                export_w = int(round(max(0.0, -(step.get("grid") or 0.0)) / slot_h * 1000 / 50) * 50)
                if f.get("house") is not None:  # what the house really uses now is covered first, the rest is sold
                    net = max(0.0, (f.get("house") or 0.0) - (f.get("pv") or 0.0))
                    export_w = int(round(max(0.0, charge_kw * 1000 - net) / 100) * 100)
            out["battery"] = {"intent": intent, "ctx": {
                "grid_charge": bool(bat.grid_charge), "min_soc": round(bat.min_soc), "soc": round(max(f["soc"] or bat.min_soc, bat.min_soc)), "target": round(b.get("target") or step["soc"]),
                "rate": round(100 * charge_kw / bat.max_charge_kw), "power_w": round(charge_kw * 1000),
                "max_power_w": round(bat.max_discharge_kw * 1000), "max_charge_w": round(bat.max_charge_kw * 1000),
                "power_kw": round(charge_kw, 2), "max_charge_kw": round(bat.max_charge_kw, 2), "max_power_kw": round(bat.max_discharge_kw, 2), "export_w": export_w,
                "device_id": getattr(self, "battery_device", None) or "", "serial": getattr(self, "battery_serial", "") or ""}}
            if "{house_w}" in str(self.profile_steps() or {}):
                # Only for profiles that use it (EcoFlow), rounded - so others aren't re-sent at every small change.
                out["battery"]["ctx"]["house_w"] = int(round((f.get("house") or 0.0) / 50) * 50)
        # The car charging on the plan's cheap power right now: the battery holds, so the car takes it from the grid.
        bw = out.get("battery")
        cw = out.get("car")
        if bw and cw and bw["intent"] == "normal" and cw["intent"] == "charge" and not self.ov.settings.get("ev_now") \
                and self.car_why.startswith("planned"):
            out["battery"] = {**bw, "intent": "hold"}
        if out.get("battery") and self.bat_parts():
            out.update(self._share(out["battery"], f))
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
            if self.engine and (pt := self.engine.power_tariff()):
                st["peak_kw"] = pt["limit_kw"]
            if st.get("ev_follow_sun") is None:
                st["ev_follow_sun"] = bool(self.ov.role("pv_power"))  # on by default when there is solar
            need = float(car.get("need_kwh") if car.get("need_kwh") is not None else 1.0)
            ev = self.ov.ev() or {}
            if ev.get("soc") is not None and ev["soc"] >= ev.get("target", 100):
                manual = False  # at its grid target: never more from the grid, even on "charge now"
                if ev["soc"] < ev.get("sun_target", ev.get("target", 100)) and st.get("ev_follow_sun"):
                    need = 1.0  # the sun's surplus may fill it further (to its own limit) - no grid hours are planned for it
                    hour, planned = None, set()
                else:
                    need = 0.0  # at its limit: it stops, in the sun too (spares the battery)
            st["onoff"] = self.onoff("car")
            st["min_a"] = adapters.lowest_amps(getattr(self, "entities", {}).get("car", []), getattr(getattr(self, "ha", None), "states", {}))
            d = decide(f, st, hour in planned, manual, need, self._sun_on)
            self._sun_on, self.car_why = d["sun"], d["why"]
            out["car"] = {"intent": "charge" if d["charge"] else "stop", "ctx": {"current": d["current"]}}
        out.update(self._more_intents(f, res, out.get("car")))
        return out

    def _share(self, want: dict[str, Any], f: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """More batteries: the same thing to all - the same level to charge to or hold at - with the power shared by
        what each can take. Battery 1 keeps its share under "battery", the others get theirs (bat2 …)."""
        from . import batteries

        s = self.ov.settings
        more = batteries.extras(s)
        c1 = float(s.get("battery_charge_kw") or 3)
        d1 = float(s.get("battery_discharge_kw") or s.get("battery_charge_kw") or 3)
        cs = [c1] + [float(b.get("charge_kw") or 3) for b in more]
        ds = [d1] + [float(b.get("discharge_kw") or b.get("charge_kw") or 3) for b in more]
        packs = f.get("batteries") or []
        ctx = want["ctx"]
        out = {}
        for i, part in enumerate(["battery", *self.bat_parts()]):
            cshare, dshare = cs[i] / sum(cs), ds[i] / sum(ds)
            share = dshare if want["intent"] == "export" else cshare
            own = packs[i]["soc"] if i < len(packs) and packs[i].get("soc") is not None else ctx["soc"]
            info = {"device": getattr(self, "battery_device", None) or "", "serial": getattr(self, "battery_serial", "") or ""} if i == 0 \
                else self.bat_info.get(part) or {}
            c = {**ctx, "soc": round(max(own, ctx.get("min_soc") or 0)), "power_w": round(ctx["power_w"] * share), "power_kw": round(ctx["power_kw"] * share, 2),
                 "max_power_w": round(ctx["max_power_w"] * dshare), "max_power_kw": round(ctx["max_power_kw"] * dshare, 2),
                 "max_charge_w": round(ctx["max_charge_w"] * cshare), "max_charge_kw": round(ctx["max_charge_kw"] * cshare, 2),
                 "export_w": int(round(ctx.get("export_w", 0) * dshare / 50) * 50),
                 "device_id": info.get("device") or "", "serial": info.get("serial") or ""}
            out[part] = {"intent": want["intent"], "ctx": c}
        return out

    def _more_intents(self, f: dict[str, Any], res: dict[str, Any], first: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
        """The extra chargers, one after the other: charger 1 comes first, then 2 … - the sun's surplus and the room
        under the main fuse that the chargers before have taken are gone for the next. So the last one is turned
        down (and stopped) first."""
        from . import chargers
        from .carspeed import VOLT, decide

        more = chargers.extras(self.ov.settings)
        if not more:
            return {}
        tz = ZoneInfo(self.ha.config.get("time_zone") or "UTC")
        now = datetime.now(tz)
        st = self.ov.settings

        def watts(want: dict[str, Any] | None, kw: float, phases: Any) -> float:
            if not want or want["intent"] != "charge":
                return 0.0
            ph = int(phases or (3 if kw > 7.5 else 1))
            return float(want["ctx"]["current"]) * VOLT * ph

        main_kw = float(st.get("charger_kw") or 7.4)
        taken = watts(first, main_kw, st.get("charger_phases"))
        cars_now = sum(max(0.0, x.get("power") or 0.0) for x in (f.get("cars") or []))
        main_now = max(0.0, (f.get("ev") or 0.0) - cars_now)  # flow's ev has all the chargers in it
        base_grid = (f.get("grid") - main_now - cars_now) if f.get("grid") is not None else None
        out = {}
        for part, c, now_c, plan in zip(self.car_parts(), more, f.get("cars") or [{}] * len(more), res.get("cars") or [{}] * len(more)):
            kw = float(c.get("charger_kw") or 7.4)
            slot = int((plan or {}).get("slot_min") or 60)
            hour = now.replace(minute=now.minute // slot * slot if slot < 60 else 0, second=0, microsecond=0)
            planned = hour in {datetime.fromisoformat(t) for t in ((plan or {}).get("hours") or [])}
            own = max(0.0, now_c.get("power") or 0.0)
            # This car sees the house as using what the chargers before it want - sun and fuse alike.
            g = None if base_grid is None else base_grid + taken + own
            flow = {"pv": f.get("pv"), "house": None if f.get("house") is None else f["house"] + taken,
                    "battery": f.get("battery"), "plug": now_c.get("plug"), "ev": own, "grid": g}
            cs = {**st, "charger_kw": kw, "charger_phases": c.get("phases"),
                  "peak_kw": (self.engine.power_tariff() or {}).get("limit_kw") if getattr(self, "engine", None) else None,
                  "ev_follow_sun": c.get("follow_sun", st.get("ev_follow_sun", bool(self.ov.role("pv_power")))), "onoff": self.onoff(part),
                  "min_a": adapters.lowest_amps(getattr(self, "entities", {}).get(part, []), getattr(getattr(self, "ha", None), "states", {}))}
            need = float((plan or {}).get("need_kwh") if (plan or {}).get("need_kwh") is not None else 1.0)
            d = decide(flow, cs, planned, bool(c.get("now")), need, self._sun_on_more.get(part, False))
            self._sun_on_more[part], self.more_why[part] = d["sun"], d["why"]
            want = {"intent": "charge" if d["charge"] else "stop", "ctx": {"current": d["current"]}}
            out[part] = want
            taken += watts(want, kw, c.get("phases"))
        return out

    def calls(self, part: str, want: dict[str, Any]) -> list[dict[str, Any]]:
        if part == "generator":
            e = self.ov.role("generator_switch")
            if not e:
                return []
            return [{"domain": e.split(".")[0], "service": "turn_on" if want["intent"] == "run" else "turn_off", "data": {"entity_id": e}}]
        if self.is_battery(part):
            steps = self.profile_steps(part) or {}
            # A profile without a way to sell runs normally instead (the plan doesn't sell then anyway).
            return self._clamp(adapters.resolve(steps.get(want["intent"]) or steps.get("normal", []), self._pool(part), want["ctx"]))
        if part.startswith("car") and part != "car":
            return self._clamp(adapters.charger_calls(want["intent"], self.entities.get(part, []), self.platforms.get(part),
                                                      want["ctx"]["current"], self.car_devices.get(part), self.ha.states,
                                                      switch=self.auto_switch(part)))
        return self._clamp(adapters.charger_calls(want["intent"], self.entities["car"], self.platforms["car"], want["ctx"]["current"],
                                                  getattr(self, "car_device", None), self.ha.states, switch=self.auto_switch("car")))

    def _clamp(self, calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Numbers within the control's own min/max - Home Assistant refuses a value outside them. A select value
        written "re:<pattern>" is the control's own option that matches (SolarAssistant names a mode its own way)."""
        out = []
        for c in calls:
            d = c["data"]
            if c.get("service") == "select_option" and str(d.get("option", "")).startswith("re:"):
                a = (self.ha.states.get(d.get("entity_id")) or {}).get("attributes") or {}
                opt = adapters.pick_option(str(d["option"])[3:], a.get("options") or [])
                if opt is None:
                    _LOGGER.warning("No option like %s on %s", d["option"][3:], d.get("entity_id"))
                    continue
                d["option"] = opt
            out.append(c)
        calls = out
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

    async def tick(self, parts: tuple[str, ...] | None = None) -> None:
        for part, want in self.intents().items():
            if parts is not None and part not in parts and not (part.startswith("car") and "car" in parts):
                continue
            mode = self.mode(part)
            if mode == "off":
                continue
            calls = self.calls(part, want)
            prev = self.last.get(part)
            changed = prev is None or prev["intent"] != want["intent"] or prev["ctx"] != want["ctx"]
            again = (adapters.PROFILES.get(self.profile_key(part) or "") or {}).get("reassert_s", REASSERT_S) if self.is_battery(part) else REASSERT_S
            due = prev is None or time.time() - prev["t"] > again  # Solis' remote control times out after 30 min
            # A value that held and then changed by itself is set again at once (at most once a minute) - the
            # inverter put back its default, or something else changed it.
            if not (changed or due) and mode == "control" and prev.get("result") == "ok" and time.time() - prev["t"] > 60:
                moved = [c["data"]["entity_id"] for c in calls if self._matches(c) is False]
                if moved:
                    now_t = time.time()
                    _LOGGER.info("%s changed back by itself - set again: %s", part, ", ".join(moved))
                    if not ((adapters.PROFILES.get(self.profile_key(part) or "") or {}).get("resets_itself") and self.is_battery(part)):
                        # (Victron puts its own defaults back - that isn't another system steering)
                        self.drift[part] = [d for d in self.drift.get(part, []) if now_t - d[0] < 3600] + [(now_t, e) for e in moved]
                    due = True
            if not (changed or due):
                continue
            entry = {"t": time.time(), "intent": want["intent"], "ctx": want["ctx"], "calls": calls, "mode": mode}
            if mode == "control" and not self.blocked(part):
                calls = calls + self._restore(part, want["intent"])
                entry["calls"] = calls
                entry["result"] = await self._send(calls)
                if entry["result"] == "ok" and want["intent"] != "export" and self.is_battery(part):
                    pool = set(self._pool(part))  # this inverter's own settings are back
                    left = {e: v for e, v in (self.ov.settings.get("restore_values") or {}).items() if e not in pool}
                    if left != (self.ov.settings.get("restore_values") or {}):
                        self.ov.save({"restore_values": left})
            elif mode == "control":
                entry["blocked"] = self.blocked(part)
            self.last[part] = entry
            if changed:
                self.log.setdefault(part, deque(maxlen=60)).appendleft(entry)

    def _restore(self, part: str, intent: str) -> list[dict[str, Any]]:
        """Settings that are the owner's own (Victron's grid setpoint, Deye's work mode): remembered before selling,
        put back when selling stops - kept on disk, so a restart in between doesn't lose them."""
        pats = ((adapters.PROFILES.get(self.profile_key(part) or "") or {}).get("restore") or []) if self.is_battery(part) else []
        if not pats:
            return []
        pool = self._pool(part)
        saved = dict(self.ov.settings.get("restore_values") or {})
        mine = {e: v for e, v in saved.items() if e in pool}  # each inverter remembers its own
        if intent == "export":
            if not mine:
                for p in pats:
                    e = adapters._find(p, pool)
                    st = (self.ha.states.get(e) or {}).get("state") if e else None
                    if e and st not in (None, "unknown", "unavailable"):
                        saved[e] = "0" if _negative(e, st) else st  # a setpoint already selling is ours, not the owner's
                if saved != (self.ov.settings.get("restore_values") or {}):
                    self.ov.save({"restore_values": saved})
            return []
        out = []
        # Not selling any more: a grid setpoint still below 0 keeps the inverter selling (Victron does exactly what it
        # is told) - back to 0, also when nothing was remembered (an older version kept a selling value as the owner's).
        for p in pats:
            e = adapters._find(p, pool)
            if e and e not in mine and _negative(e, (self.ha.states.get(e) or {}).get("state")):
                mine[e] = "0"
        for e, v in mine.items():
            if _negative(e, v):
                v = "0"
            if e.startswith("select."):
                out.append({"domain": "select", "service": "select_option", "data": {"entity_id": e, "option": v}})
            elif e.startswith("switch."):
                if v in ("on", "off"):
                    out.append({"domain": "switch", "service": f"turn_{v}", "data": {"entity_id": e}})
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
        e = data.get("entity_id")
        if c.get("service") in ("turn_on", "turn_off") and isinstance(e, str) and e.split(".")[0] in ("switch", "input_boolean"):
            state = (self.ha.states.get(e) or {}).get("state")
            return None if state not in ("on", "off") else state == c["service"][5:]  # a switch already on/off: not sent again
        want = data.get("option", data.get("value"))
        if not isinstance(e, str) or want is None or e not in self.ha.states:
            return None
        state = self.ha.states[e].get("state")
        try:
            return abs(float(state) - float(want)) <= 0.6
        except (TypeError, ValueError):
            return str(state) == str(want)

    OTHER = 3  # changed back this many times in an hour: something else is steering too

    def watch_checks(self) -> list[dict[str, Any]]:
        """Warnings for the self-check: another system steers the battery too (Predbat, an automation, the inverter's
        own schedule) - they work against each other."""
        out = []
        now_t = time.time()
        for part, seen in self.drift.items():
            recent = [e for t, e in seen if now_t - t < 3600]
            if self.mode(part) == "control" and len(recent) >= self.OTHER:
                names = ", ".join(sorted({e.split(".", 1)[1] for e in recent}))
                out.append({"key": "other_control", "level": "warn", "vals": {"list": names}, "goto": "battery"})
        pm = str((self.ha.states.get("select.predbat_mode") or {}).get("state") or "")
        if self.mode("battery") == "control" and pm and pm.lower() not in ("monitor", "unavailable", "unknown"):
            out.append({"key": "predbat_on", "level": "warn", "vals": {"mode": pm}, "goto": "battery"})
        return out

    def _took(self, calls: list[dict[str, Any]]) -> bool:
        """Did the controls take the values? (Selects and numbers that can be read back.)"""
        return all(self._matches(c) is not False for c in calls)

    async def release(self) -> None:
        """Back to shadow: the battery is put back to normal first, the charger is left as it is."""
        wants = self.intents()
        for part in ["battery", *self.bat_parts()]:
            if self.mode(part) == "control" and not self.blocked(part) and (want := wants.get(part)):
                await self._send(self.calls(part, {**want, "intent": "normal"}) + self._restore(part, "normal"))
        modes = {p: "shadow" for p in self.parts()}
        self.ov.save({"control": modes})
        self.last.clear()

    def status(self) -> dict[str, Any]:
        wants = self.intents()
        out = {}
        from . import chargers

        names = {p: c.get("name") or "" for p, c in zip(self.car_parts(), chargers.extras(self.ov.settings))}
        for part in self.parts():
            want = wants.get(part)
            out[part] = {
                "mode": self.mode(part), "blocked": self.blocked(part), "now": want,
                "calls": self.calls(part, want) if want else [], "log": list(self.log.get(part, []))[:20],
                "entities": self.entities.get(part, []),
            }
            if part in names:
                out[part].update(name=names[part], why=self.more_why.get(part, ""))
            if part.startswith("bat"):
                key = self.profile_key(part)
                prof = adapters.PROFILES.get(key or "") or {}
                out[part].update(name=self._extra_battery(part).get("name") or "", profile={
                    "key": key, "name": prof.get("name"), "model": (self.bat_info.get(part) or {}).get("model"),
                    "tested": bool(prof.get("tested")) if key else None, "check": self.check(part)})
        out["car_parts"] = self.car_parts()
        out["bat_parts"] = self.bat_parts()
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


def _negative(entity: str, value: Any) -> bool:
    """A grid setpoint below 0: the inverter sells to the grid."""
    if not entity.startswith("number.") or not re.search(r"grid_set_?point|acpowersetpoint", entity):
        return False
    try:
        return float(value) < 0
    except (TypeError, ValueError):
        return False

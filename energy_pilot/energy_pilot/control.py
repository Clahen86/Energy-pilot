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
import math
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
RATE_BAND = 5  # % of the charge power: a smaller change while charging isn't written (fewer writes to the inverter)
TARGET_BAND = 3  # % on the stop level, likewise - as long as the battery isn't close to the old one


def steady(prev: dict | None, want: dict) -> dict:
    """While the battery charges from the grid, small changes in the power and the stop level are left out: the old
    values are kept, so nothing new is written. A change of intent, or a bigger step, goes through as always."""
    if not prev or prev.get("intent") != "charge" or want.get("intent") != "charge":
        return want
    old, new = prev.get("ctx") or {}, dict(want.get("ctx") or {})
    try:
        # The rate is a share of the battery's top power: a new top (set by the user) at the same share is a new power
        # all the same, and goes through (DK Deye, 2026-11-27: 7 kW -> 5 kW at 100 % kept the old current).
        same_top = old.get("max_charge_w") == new.get("max_charge_w")
        if same_top and abs(float(new["rate"]) - float(old["rate"])) < RATE_BAND:
            for k in ("rate", "power_w", "power_kw", "charge_a"):
                if k in old:
                    new[k] = old[k]
        if abs(float(new["target"]) - float(old["target"])) <= TARGET_BAND and float(old["target"]) >= float(new.get("soc") or 0) + 2:
            new["target"] = old["target"]
    except (KeyError, TypeError, ValueError):
        return want
    return {**want, "ctx": new}


YAML_CONTROLS = re.compile(r"^(select\.(ems_mode|battery_forced_charge_discharge)|number\.battery_(forced_charge_discharge_power|"
                           r"max_charge_power|max_discharge_power|min_soc|max_soc))$")



# A shared fix (from other installations) may only name the same kind of mode: never the other way (charging made
# discharging or selling, or back), and never a mode that could take the house off the grid or stop the inverter.
_OUT = re.compile(r"dis.?charg|export|sell|feed|discharge", re.I)
_IN = re.compile(r"(?<!dis)(?<!dis_)(?<!dis-)(?<!dis )charg|import|buy", re.I)


def safe_shared_fix(intent: str, frm: str, to: str) -> bool:
    from .selftest import UNSAFE

    if UNSAFE.search(to):
        return False
    if intent in ("charge", "hold", "normal", "start") and _OUT.search(to) and not _OUT.search(frm):
        return False
    if intent in ("export", "stop") and _IN.search(to) and not _IN.search(frm):
        return False
    return True

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
        self._phase_at: dict[str, float] = {}  # when each charger last changed between 1 and 3 phases
        self.car_why = ""
        self.lone_ok: dict[str, bool] = {}  # a charger's only switch may start it (found on its own device)
        self.chosen: dict[str, str] = {}  # the switch picked for a charger in the settings
        self.switch_options: list[dict[str, Any]] = []
        self._devices: dict[str, dict[str, Any]] = {}
        self.registry: list[dict[str, Any]] = []
        self.discovered = False  # the controls looked up at least once since the start
        self.thing_candidates: list[dict[str, Any]] = []  # machines and small batteries worth offering (things.find)
        # Controls that went back to another value after they were set (Victron's defaults, Predbat, an automation):
        # part -> [(time, entity)], the last hour.
        self.drift: dict[str, list[tuple[float, str]]] = {}
        self._gone: dict[str, set[str]] = {}  # controls seen unavailable since the last send (sent again when back)
        self.testing: set[str] = set()  # parts the self-test drives right now - left alone meanwhile
        self.community_used: dict[str, dict[str, Any]] = {}  # shared fixes in use here (shown with an undo)
        self.safe_until: dict[str, float] = {}  # the battery did the opposite of what it was told: normal until then
        self._wrong: dict[str, float] = {}
        self._car_idle: dict[str, float] = {}
        self._kicked: dict[str, bool] = {}
        self.car_stuck: dict[str, bool] = {}
        self._bat_lock = asyncio.Lock()  # the battery's round and the minute's keep-alive never send at once

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
        would go on selling in shadow). A charger with its own planning (evcc) gets it back."""
        if self.mode(part) != "control" or self.blocked(part):
            return
        if part.startswith("car"):
            if calls := self._charger_hand_back(part):
                await self._send(self._clamp(calls))
            return
        if not self.is_battery(part):
            return
        want = self.intents().get(part)
        if want:
            await self._send(self.calls(part, {**want, "intent": "normal"}) + self._restore(part, "normal"))

    def _charger_hand_back(self, part: str) -> list[dict[str, Any]]:
        return adapters.charger_hand_back(self.platforms.get(part), self.entities.get(part, []))

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
        self._ent_reg = by_id  # (the setup for the developer: setupinfo.py)
        # Entity ids in the user's language: the integration's own key as a second name the profiles match too.
        adapters.ALIASES = {e["entity_id"]: a for e in entities if (a := adapters.alias_for(e["entity_id"], e.get("translation_key")))}
        self.phones = {e["entity_id"] for e in entities if e.get("platform") == "mobile_app"}  # phones and tablets
        try:
            devices = {d["id"]: d for d in await self.ha.command({"type": "config/device_registry/list"})}
            self._devices = devices
            dev = devices.get((by_id.get(self.ov.role("battery_soc") or "") or {}).get("device_id") or "") or {}
            parts = [x for x in (dev.get("model"), dev.get("model_id"), dev.get("name")) if x]
            self.model = " ".join(dict.fromkeys(parts)) or None  # "Growatt SPH", not "Growatt SPH Growatt SPH"
        except Exception:  # noqa: BLE001
            self.model = None
        try:  # the areas' names: taken out of the names sent to the developer (setupinfo.py)
            self._areas = [a.get("name") or "" for a in await self.ha.command({"type": "config/area_registry/list"})]
        except Exception:  # noqa: BLE001
            self._areas = []
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
            found = [e["entity_id"] for e in entities if not e.get("disabled_by") and e["entity_id"].split(".")[0] in ("select", "number", "switch", "button", "time")
                     and ((dev and e.get("device_id") == dev) or (plat and e.get("platform") == plat and plat not in GENERIC_PLATFORMS
                                                                   and not (part == "car" and dev)))]
            # The charger: only its own device when it has one - Tuya, say, also has the air conditioner and the cat's
            # litter box, and their switches must never be taken for the charger's.
            if not found and anchor and part == "battery":  # MQTT inverters: same name prefix (never for a charger)
                prefix = anchor.split(".", 1)[1].split("_")[0]
                found = [e for e in self.ha.states if e.split(".")[0] in ("select", "number", "switch") and e.split(".", 1)[1].startswith(prefix + "_")]
            if part == "battery" and (not dev or plat in ("modbus", "template")):
                # mkaiser's Sungrow package (and YAML inverters like it): its battery controls are template selects
                # and numbers without a device - picked up by their fixed names.
                found += [e["entity_id"] for e in entities if not e.get("disabled_by") and e["entity_id"] not in found
                          and YAML_CONTROLS.match(e["entity_id"])]
            if part == "battery" and not found:
                # The battery read from one integration (SolaX's own, local) and steered through another (SolaX
                # Modbus) on a device of its own: the controls of the chosen profile's integration - or of the one
                # inverter integration here that has controls.
                p = adapters.PROFILES.get(self.ov.settings.get("inverter_profile") or "") or {}
                chosen = p.get("platform") or self.ov.settings.get("inverter_profile")
                known = {k for k in adapters.PROFILES} | {q.get("platform") for q in adapters.PROFILES.values() if q.get("platform")}
                ctl = [e for e in entities if not e.get("disabled_by") and e["entity_id"].split(".")[0] in ("select", "number", "switch", "button", "time")
                       and e.get("platform") in known and e.get("platform") not in GENERIC_PLATFORMS]
                have = {e.get("platform") for e in ctl}
                pick = chosen if chosen in have else (next(iter(have)) if len(have) == 1 else None)
                if pick:
                    found = [e["entity_id"] for e in ctl if e.get("platform") == pick]
                    plat = pick
            # The anchor's own device first: with two inverters on one integration (a Kostal G3 and a Plenticore Plus)
            # a profile's pattern then finds this one's controls, not whichever sorts first.
            own = {e["entity_id"] for e in entities if dev and e.get("device_id") == dev}
            self.entities[part], self.platforms[part] = sorted(found, key=lambda e: (e not in own, e)), plat
            if part == "car":
                self.car_device = dev  # Easee's actions want the charger's device
                self.lone_ok["car"] = bool(dev)
            if part == "battery":
                self.battery_device = dev  # for services that want the device (Huawei, GivEnergy)
                d = (devices or {}).get(dev or "") if "devices" in dir() else None
                self.battery_serial = (d or {}).get("serial_number") or ""  # Alpha ESS wants the serial

        self._mend_wrong_profile()

        # The extra chargers: the controls on the device of their power (or plug) sensor.
        from . import chargers

        for part, c in zip(self.car_parts(), chargers.extras(self.ov.settings)):
            anchor = c.get("power") or c.get("plug")
            dev = (by_id.get(anchor) or {}).get("device_id")
            plat = (by_id.get(anchor) or {}).get("platform")
            found = [e["entity_id"] for e in entities if not e.get("disabled_by") and dev and e.get("device_id") == dev
                     and e["entity_id"].split(".")[0] in ("select", "number", "switch", "button", "time")]
            self.entities[part], self.platforms[part], self.car_devices[part] = sorted(found), plat, dev
            self.lone_ok[part] = bool(dev)

        # The switch chosen for a charger (Settings → Car → Control): it starts and stops the car, and a current
        # control on its device (Tuya Local, ESPHome …) sets the speed. Only charging switches are offered.
        skip = {d for d in [getattr(self, "battery_device", None)] if d}
        self.registry = entities  # for Settings → Runs cheaply (what to pick from)
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
            found = [e["entity_id"] for e in entities if not e.get("disabled_by") and e["entity_id"].split(".")[0] in ("select", "number", "switch", "button", "time")
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
            # A known charger integration (Wallbox, Zaptec, Peblar …) keeps its own way even with its switch chosen by
            # hand - the generic way paused a Wallbox and lost Zaptec's services. Else the switch and a current control.
            plat = reg.get("platform") if reg.get("platform") in adapters.CHARGER_SERVICES else None
            if plat is None and self.platforms.get(part) in adapters.CHARGER_SERVICES:
                # The owner's own start/stop switch (a template, a script) beside a known charger (Easee): the
                # charger keeps its own way - current, pause, resume - and the switch is used as well.
                self.entities[part] = sorted(set(self.entities.get(part) or []) | {sw})
                self.chosen[part] = sw
                continue
            kinds = r"(number|select|switch|button)\." if plat else r"(number|select)\."
            own = [e["entity_id"] for e in entities if not e.get("disabled_by") and dev and e.get("device_id") == dev
                   and re.match(kinds, e["entity_id"])]
            self.entities[part] = sorted(set(own) | {sw})
            self.platforms[part], self.chosen[part] = plat, sw
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

    def _mend_wrong_profile(self) -> None:
        """A profile chosen by hand that finds none of its controls, while another one fits (Fox ESS Modbus with the
        cloud profile chosen): the one that fits is taken - saved, so the choice shows it and the change log says who."""
        chosen = self.ov.settings.get("inverter_profile")
        p = adapters.PROFILES.get(chosen or "")
        ents = self.entities.get("battery") or []
        if not p or not ents:
            return
        need = [s[0] for steps in (p["normal"], p["hold"], p["charge"]) for s in steps
                if s[1] not in ("service", "grid") and s[0] not in (p.get("optional") or [])]
        if not need or any(adapters.hit(pat, e) for pat in need for e in ents):
            return
        guess = adapters.guess_profile(ents, {self.platforms.get("battery") or ""}, self.model)
        if guess and guess != chosen:
            _LOGGER.warning("Profile %s finds none of its controls here - %s fits, and is used instead", chosen, guess)
            self.ov.save({"inverter_profile": guess}, "energy_pilot")

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

    def sun_through_ac(self) -> bool:
        """A hybrid: the sun goes out through the inverter's AC side with the battery, so both share its AC power.
        The profile's "sun_ac" is a pattern on the model (an AC-coupled battery inverter of the same make is not)."""
        pat = (adapters.PROFILES.get(self.profile_key("battery") or "") or {}).get("sun_ac")
        return bool(pat) and re.search(pat, str(getattr(self, "model", None) or ""), re.I) is not None

    def can_block_sun(self) -> bool:
        """The inverter's hold sets how much it may charge, or it has a hold of its own for selling the sun (Kostal's
        Block Charge) - then the sun can be kept out of the battery."""
        steps = self.profile_steps() or {}
        hold = str(steps.get("hold") or "")
        return bool(steps.get("hold_sun")) or "{max_charge_w}" in hold or "{max_charge_kw}" in hold

    def _selling_sun_pays(self, steps: list[dict[str, Any]], bat: Any) -> bool:
        """Does selling the sun's surplus now beat storing it? The plan moves in whole steps of the level (2 % of a big
        battery is about 1 kWh), so a surplus smaller than a step shows as a hold that sells - not as a choice. A kWh of
        sun stored saves the cheapest later hour the plan buys for the house in (after the round trip and the wear);
        selling must beat that, or the sun goes into the battery as before. Nothing bought later: selling it is fine."""
        plan = getattr(self.ov, "plan", None)
        try:
            hours = {datetime.fromisoformat(h["t"]): h for h in ((plan() or {}).get("hours") or [])} if callable(plan) else {}
            hour = lambda t: datetime.fromisoformat(t).replace(minute=0, second=0, microsecond=0)  # noqa: E731
            sell = (hours.get(hour(steps[0]["t"])) or {}).get("sell")
            later = [hours[hour(s["t"])]["price"] for s in steps[1:]
                     if (s.get("grid") or 0.0) > 0.01 and s.get("action") != "charge_grid"
                     and hours.get(hour(s["t"]), {}).get("price") is not None]
        except (KeyError, TypeError, ValueError):
            return True
        if sell is None or not later:
            return True
        return sell >= bat.efficiency * min(later) - 2 * bat.wear

    def profile_steps(self, part: str = "battery") -> dict[str, list] | None:
        key = self.profile_key(part)
        if key == "custom" and part == "battery":
            c = self.ov.settings.get("custom_profile") or {}
            steps = {i: [(s["entity"], s["kind"], s.get("value")) for s in c.get(i, []) if s.get("entity")] for i in ("normal", "hold", "charge", "export")}
            steps = {i: v for i, v in steps.items() if v or i != "export"}
            return steps if any(steps.values()) else None
        p = adapters.PROFILES.get(key or "")
        return {i: p[i] for i in ("normal", "hold", "hold_sun", "charge", "export") if i in p} if p else None

    def max_power_kw(self, part: str = "battery") -> float | None:
        """The most the inverter lets the battery charge or discharge, in kW - a profile's "max_power" sensor (Kostal
        works it out from the battery's voltage and current), the anchor's own device first. None: none found."""
        st = self._profile_state("max_power", part)
        try:
            v = float(st.get("state"))
        except (TypeError, ValueError):
            return None
        unit = str((st.get("attributes") or {}).get("unit_of_measurement") or "W")
        kw = v if unit.lower() == "kw" else v / 1000
        return round(kw, 2) if kw > 0 else None

    def fuse_amps(self, part: str = "battery") -> float | None:
        """The house's main fuse in amps as the inverter's integration knows it - a profile's "fuse" number (Kostal's
        House Fuse Size, which its own grid protection uses), the anchor's own device first. None: none found."""
        try:
            v = float(self._profile_state("fuse", part).get("state"))
        except (TypeError, ValueError):
            return None
        return v if 0 < v <= 1000 else None

    def _profile_state(self, key: str, part: str = "battery") -> dict[str, Any]:
        """The state of the entity a profile names under key (a pattern): the anchor's own device first, then any."""
        pat = (adapters.PROFILES.get(self.profile_key(part) or "") or {}).get(key)
        if not pat:
            return {}
        reg = getattr(self, "_ent_reg", None) or {}
        dev = getattr(self, "battery_device", None) if part == "battery" else None
        cands = sorted(e for e in self.ha.states if adapters.hit(pat, e))
        own = [e for e in cands if dev and (reg.get(e) or {}).get("device_id") == dev]
        e = (own or cands or [None])[0]
        return (self.ha.states.get(e) or {}) if e else {}

    def ready(self, part: str = "battery") -> bool | None:
        """Is the inverter up and able to obey? A profile's "ready" (sensor pattern, state pattern) - a Kostal asleep
        at night first runs its start-up and grid checks, several minutes. None: the profile has no such sensor or it
        was not found."""
        r = (adapters.PROFILES.get(self.profile_key(part) or "") or {}).get("ready")
        if not r:
            return None
        sensor, want = r
        reg = getattr(self, "_ent_reg", None) or {}
        dev = getattr(self, "battery_device", None) if part == "battery" else None
        cands = [e for e in self.ha.states if adapters.hit(sensor, e)]
        own = [e for e in cands if dev and (reg.get(e) or {}).get("device_id") == dev]
        e = (own or cands or [None])[0]
        st = str((self.ha.states.get(e) or {}).get("state", "")) if e else ""
        if not e or st in ("", "unknown", "unavailable"):
            return None
        return bool(re.search(want, st))

    def soc_limits(self, part: str = "battery") -> tuple[float | None, float | None]:
        """(lowest, highest) % the inverter lets the battery go to - a profile's "limits" (minimum and maximum number
        patterns), the anchor's own device first. None where the profile has none or the value can't be read."""
        r = (adapters.PROFILES.get(self.profile_key(part) or "") or {}).get("limits")
        if not r:
            return None, None
        out: list[float | None] = []
        for pat in r:
            e = next((x for x in self.entities.get(part, []) if adapters.hit(pat, x)), None)
            try:
                v = float((self.ha.states.get(e) or {}).get("state")) if e else None
            except (TypeError, ValueError):
                v = None
            out.append(v if v is not None and 0 <= v <= 100 else None)
        return out[0], out[1]

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
            extra = [e for e in self.ha.states if e not in own and e.split(".")[0] in ("select", "number", "switch", "button", "time")
                     and any(adapters.hit(p, e) for p in pats)]
            return own + sorted(extra)
        return own

    # ---------- deciding and acting ----------

    def _windows(self, b: dict[str, Any], step: dict[str, Any]) -> dict[str, str]:
        """The inverter's time windows for the plan's block now: from where the block began (remembered, or a little
        before now) to where the same action ends in the plan. The same while the block lasts - nothing to rewrite."""
        now = datetime.now(ZoneInfo(self.ha.config.get("time_zone") or "UTC"))
        act = step.get("action")
        end = None
        try:
            run = 0
            for s in b.get("steps") or []:
                if s.get("action") != act:
                    break
                run += 1
            if run:
                last = datetime.fromisoformat(b["steps"][run - 1]["t"]).astimezone(now.tzinfo)
                end = last + timedelta(minutes=b.get("slot_min") or 60)
        except (KeyError, TypeError, ValueError):
            end = None
        blk = getattr(self, "_block", None)
        if not (blk and blk[0] == act and blk[1] <= now and blk[1].date() == now.date()):
            blk = self._block = (act, adapters.window_start(now))
        return adapters.alpha_windows(now, blk[1], end if act in ("charge_grid", "export") else None)

    def intents(self) -> dict[str, dict[str, Any]]:
        res = (self.engine.result or {}) if self.engine else {}
        out: dict[str, dict[str, Any]] = {}
        f = self.ov.flow()
        b = res.get("battery")
        if not (b and b.get("steps")) and self.engine and (getattr(self.ov, "price_info", None) or {}).get("none") \
                and f.get("soc") is not None:
            # No prices anywhere, so no plan: the battery isn't left in its last order (a grid charge would run on
            # without a price) - it runs as normal, the house first, until the prices are back and the plan takes over.
            b = {"steps": [{"t": datetime.now(ZoneInfo(self.ha.config.get("time_zone") or "UTC")).isoformat(), "action": "normal",
                            "soc": f["soc"], "grid": 0.0}], "slot_min": 60, "target": f["soc"]}
        if b and b.get("steps"):
            step = b["steps"][0]
            bat = self.engine.settings()
            intent = {"charge_grid": "charge", "hold": "hold", "export": "export"}.get(step["action"], "normal")
            # A hold only because the sun was to cover the house (nothing bought in the plan): the battery runs as
            # normal - the same in the plan, but when the house uses more than foreseen it comes from the battery,
            # not the grid. Not when the sun's surplus is to be sold instead of stored (below).
            sells_sun = (step.get("grid") or 0.0) < -0.01 and getattr(self.ov, "sell_sun", lambda: False)() and self.can_block_sun() \
                and step["action"] == "hold" and self._selling_sun_pays(b["steps"], bat)
            if intent == "hold" and (step.get("grid") or 0.0) <= 0.01 and not sells_sun:
                intent = "normal"
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
            if intent == "charge" and bat.import_limit_kw and f.get("house") is not None:
                # The plan counted on what the house was expected to use; the oven and the kettle on at once can take
                # the house over the import limit (the main fuse, a contract's cap) while the battery charges. The
                # charge gives way to what the house really uses now - the car's charging does the same (carspeed.py).
                ev_apart = 0.0 if (self.engine and self.engine.ev_in_house()) else float(f.get("ev") or 0.0)
                use_kw = max(0.0, float(f.get("house") or 0.0) + ev_apart - float(f.get("pv") or 0.0)) / 1000
                room = bat.import_limit_kw - use_kw - 0.2  # a little margin for the next minute
                if room < charge_kw:
                    if room < 0.3:
                        intent, charge_kw = "hold", 0.5  # no room at all: wait, the plan picks it up again
                    else:
                        charge_kw = math.floor(room * 10) / 10  # in 100 W steps, not re-sent at every wobble
            export_w = 0
            if intent == "export":  # the battery's discharge power: the house's share and what is sold
                charge_kw = min(bat.max_discharge_kw, max(0.5, ((f["soc"] or 0) - step["soc"]) / 100 * bat.capacity_kwh / left_h))
                export_w = int(round(max(0.0, -(step.get("grid") or 0.0)) / slot_h * 1000 / 50) * 50)
                if f.get("house") is not None:  # what the house really uses now is covered first, the rest is sold
                    net = max(0.0, (f.get("house") or 0.0) - (f.get("pv") or 0.0))
                    export_w = int(round(max(0.0, charge_kw * 1000 - net) / 100) * 100)
            out["battery"] = {"intent": intent, "ctx": {
                "grid_charge": bool(bat.grid_charge), "min_soc": round(bat.min_soc), "soc": round(max(f["soc"] or bat.min_soc, bat.min_soc)), "soc_floor": int(max(f["soc"] or bat.min_soc, bat.min_soc)), "target": round(b.get("target") or step["soc"]),
                "rate": round(100 * charge_kw / bat.max_charge_kw), "power_w": round(charge_kw * 1000),
                "max_power_w": round(bat.max_discharge_kw * 1000), "max_charge_w": round(bat.max_charge_kw * 1000),
                "power_kw": round(charge_kw, 2), "max_charge_kw": round(bat.max_charge_kw, 2), "max_power_kw": round(bat.max_discharge_kw, 2), "export_w": export_w,
                "device_id": getattr(self, "battery_device", None) or "", "serial": getattr(self, "battery_serial", "") or "",
                **self._windows(b, step)}}
            if any("{charge_a}" in str(self.profile_steps(p) or {}) for p in ["battery", *self.bat_parts()]):
                # Deye limits charging from the grid by a current: the planned power over the battery's voltage.
                out["battery"]["ctx"]["charge_a"] = max(1, round(charge_kw * 1000 / self._battery_volt()))
            if "{house_w}" in str(self.profile_steps() or {}):
                # Only for profiles that use it (EcoFlow), rounded - so others aren't re-sent at every small change.
                out["battery"]["ctx"]["house_w"] = int(round((f.get("house") or 0.0) / 50) * 50)
            # The plan holds while the sun has a surplus it sells: the battery mustn't fill up with it anyway (a plain
            # hold still takes the sun). Only inverters whose hold sets the charge limit can do this.
            if intent == "hold" and sells_sun:
                out["battery"]["ctx"].update(max_charge_w=0, max_charge_kw=0, sell_sun=True)
        # The car charging: the battery plan has its charge in (engine.car_load) and decides itself whether the
        # battery helps it or holds - no fixed rule here.
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
            from .powertariff import counts

            if self.engine and (pt := self.engine.power_tariff()) and counts(st, datetime.now(self.engine.tz)):
                st["peak_kw"] = pt["limit_kw"]  # (a free hour - night, weekend - has no peak to keep under)
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
            if self.engine and f.get("soc") is not None:
                bat = self.engine.settings()
                if not bat.grid_charge and f["soc"] < bat.max_soc - 1:
                    st["batt_sun_w"] = bat.max_charge_kw * 1000  # only the sun can fill it: it gets the sun first
            st["min_a"] = adapters.lowest_amps(getattr(self, "entities", {}).get("car", []), getattr(getattr(self, "ha", None), "states", {}))
            st.update(self._phase_settings("car", st))
            d = decide(f, st, hour in planned, manual, need, self._sun_on)
            self._sun_on, self.car_why = d["sun"], d["why"]
            self._phase_seen("car", st, d.get("phases"))
            out["car"] = {"intent": "charge" if d["charge"] else "stop", "ctx": {"current": d["current"], **({"phases": d["phases"]} if d.get("phases") else {})}}
        out.update(self._more_intents(f, res, out.get("car")))
        return out

    def _share(self, want: dict[str, Any], f: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """More batteries: the same thing to all - the same level to charge to or hold at - with the power shared by
        what each can take. Battery 1 keeps its share under "battery", the others get theirs (bat2 …)."""
        from . import batteries

        s = self.ov.settings
        more = batteries.extras(s)
        c1, d1 = batteries.main_kw(s, self.max_power_kw())
        cs = [c1] + [float(b.get("charge_kw") or 3) for b in more]
        ds = [d1] + [float(b.get("discharge_kw") or b.get("charge_kw") or 3) for b in more]
        packs = f.get("batteries") or []
        ctx = want["ctx"]
        out = {}
        # Running on their own, two batteries each keep the grid at zero: one empties into the house while the other
        # (that sees it as sun - a SolarEdge on a Victron's AC-out) fills up from it, losing power both ways. With no
        # sun to spare, none of them may charge on "normal" - the house is covered, and nothing goes round in a circle.
        pv, house = float(f.get("pv") or 0.0), float(f.get("house") or 0.0) + float(f.get("ev") or 0.0)
        no_spare_sun = want["intent"] == "normal" and pv - house < 100
        for i, part in enumerate(["battery", *self.bat_parts()]):
            cshare, dshare = cs[i] / sum(cs), ds[i] / sum(ds)
            share = dshare if want["intent"] == "export" else cshare
            own = packs[i]["soc"] if i < len(packs) and packs[i].get("soc") is not None else ctx["soc"]
            info = {"device": getattr(self, "battery_device", None) or "", "serial": getattr(self, "battery_serial", "") or ""} if i == 0 \
                else self.bat_info.get(part) or {}
            c = {**ctx, "soc": round(max(own, ctx.get("min_soc") or 0)), "soc_floor": int(max(own, ctx.get("min_soc") or 0)), "power_w": round(ctx["power_w"] * share), "power_kw": round(ctx["power_kw"] * share, 2),
                 "max_power_w": round(ctx["max_power_w"] * dshare), "max_power_kw": round(ctx["max_power_kw"] * dshare, 2),
                 "max_charge_w": round(ctx["max_charge_w"] * cshare), "max_charge_kw": round(ctx["max_charge_kw"] * cshare, 2),
                 "export_w": int(round(ctx.get("export_w", 0) * dshare / 50) * 50),
                 **({"charge_a": max(1, round(ctx["charge_a"] * cshare))} if "charge_a" in ctx else {}),
                 "device_id": info.get("device") or "", "serial": info.get("serial") or ""}
            if no_spare_sun:
                c.update(max_charge_w=0, max_charge_kw=0)
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
        taken = watts(first, main_kw, ((first or {}).get("ctx") or {}).get("phases") or st.get("charger_phases"))
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
            cs["ev_mode"] = c.get("mode")  # each charger's own Cheapest/Sun choice
            cs.update(self._phase_settings(part, cs))
            need = float((plan or {}).get("need_kwh") if (plan or {}).get("need_kwh") is not None else 1.0)
            d = decide(flow, cs, planned, bool(c.get("now")), need, self._sun_on_more.get(part, False))
            self._sun_on_more[part], self.more_why[part] = d["sun"], d["why"]
            self._phase_seen(part, cs, d.get("phases"))
            want = {"intent": "charge" if d["charge"] else "stop", "ctx": {"current": d["current"], **({"phases": d["phases"]} if d.get("phases") else {})}}
            out[part] = want
            taken += watts(want, kw, d.get("phases") or c.get("phases"))
        return out

    PHASE_HOLD_S = 600  # at most one change between 1 and 3 phases per 10 minutes (the car pauses at each)

    def _phase_settings(self, part: str, st: dict[str, Any]) -> dict[str, Any]:
        """What decide() needs to switch phases - only with the setting on and a phase choice on the charger."""
        if not st.get("ev_phase_switch"):
            return {}
        pc = adapters.phase_control(self.entities.get(part, []), self.ha.states)
        if not pc:
            return {}
        held = time.time() - self._phase_at.get(part, 0) < self.PHASE_HOLD_S
        return {"phase_switch": True, "phase_now": pc["now"], "phase_lock": held and pc["now"] is not None}

    def _phase_seen(self, part: str, st: dict[str, Any], phases: int | None) -> None:
        if phases and st.get("phase_switch") and st.get("phase_now") and phases != st["phase_now"]:
            self._phase_at[part] = time.time()

    def _phase_call(self, part: str, want: dict[str, Any]) -> list[dict[str, Any]]:
        ph = (want.get("ctx") or {}).get("phases")
        if want.get("intent") != "charge" or ph not in (1, 3):
            return []
        pc = adapters.phase_control(self.entities.get(part, []), self.ha.states)
        if not pc:
            return []
        if pc.get("switch"):
            return [{"domain": "switch", "service": f"turn_{pc[str(ph)]}", "data": {"entity_id": pc["entity"]}}]
        return [{"domain": "select", "service": "select_option", "data": {"entity_id": pc["entity"], "option": pc[str(ph)]}}]

    def calls(self, part: str, want: dict[str, Any]) -> list[dict[str, Any]]:
        if part == "generator":
            e = self.ov.role("generator_switch")
            if not e:
                return []
            return [{"domain": e.split(".")[0], "service": "turn_on" if want["intent"] == "run" else "turn_off", "data": {"entity_id": e}}]
        if self.is_battery(part):
            steps = self.profile_steps(part) or {}
            # A profile without a way to sell runs normally instead (the plan doesn't sell then anyway). Holding while
            # the sun is sold: the profile's own hold for that, when it has one (Kostal's Block Charge).
            key = want["intent"]
            if key == "hold" and want["ctx"].get("sell_sun") and steps.get("hold_sun"):
                key = "hold_sun"
            calls = self._clamp(adapters.resolve(steps.get(key) or steps.get("normal", []), self._pool(part), want["ctx"]))
            return self._fixed(part, want["intent"], calls)
        if part.startswith("car") and part != "car":
            return self._phase_call(part, want) + self._clamp(adapters.charger_calls(
                want["intent"], self.entities.get(part, []), self.platforms.get(part), want["ctx"]["current"],
                self.car_devices.get(part), self.ha.states, switch=self.auto_switch(part), chosen=self.chosen.get(part)))
        calls = self._clamp(adapters.charger_calls(
            want["intent"], self.entities["car"], self.platforms["car"], want["ctx"]["current"],
            getattr(self, "car_device", None), self.ha.states, switch=self.auto_switch("car"), chosen=self.chosen.get("car")))
        # The charger test's steps are "start"/"stop" (selftest.py): an option it - or 3 other installations with the
        # same charger - found works is used instead.
        return self._phase_call("car", want) + self._fixed("car", "start" if want["intent"] == "charge" else "stop", calls)

    def _clamp(self, calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Numbers within the control's own min/max - Home Assistant refuses a value outside them. A select value
        written "re:<pattern>" is the control's own option that matches (SolarAssistant names a mode its own way); any
        other option not in the control's list is matched to it ignoring case, spaces and underscores."""
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
            elif c.get("service") == "select_option" and d.get("option") is not None:
                # A profile's option written as the label ("Maximise self consumption") where the integration has
                # the value ("maximise_self_consumption"), or the other way round: the control's own one is used.
                opts = ((self.ha.states.get(d.get("entity_id")) or {}).get("attributes") or {}).get("options") or []
                if opts and d["option"] not in opts:
                    key = re.sub(r"[^a-z0-9]", "", str(d["option"]).lower())
                    d["option"] = next((o for o in opts if re.sub(r"[^a-z0-9]", "", str(o).lower()) == key), d["option"])
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
        testing = getattr(self, "testing", set())
        for part, want in self.intents().items():
            if part in testing or (part.startswith("car") and "car" in testing):
                continue  # the test drives it now (selftest.py)
            if time.time() < getattr(self, "safe_until", {}).get(part, 0) and want.get("intent") not in (None, "normal"):
                want = {**want, "intent": "normal"}  # it did the opposite of what it was told: safe until checked
            if parts is not None and part not in parts and not (part.startswith("car") and "car" in parts):
                continue
            mode = self.mode(part)
            if mode == "off":
                continue
            prev = self.last.get(part)
            if self.is_battery(part):
                want = steady(prev, want)
            calls = self.calls(part, want)
            prof = self._prof(part)
            # Changed when something else would be written: the level or a clock in the context that no call uses
            # (the battery's level while it charges) is no reason to write the same values again. An inverter that
            # forgets (Victron) gets everything again on any change, as before.
            changed = prev is None or prev["intent"] != want["intent"] or (prev["ctx"] != want["ctx"] and (
                (self._forced(prof) and self.is_battery(part)) or self.calls(part, prev) != calls))
            again = prof.get("reassert_s", REASSERT_S) if self.is_battery(part) else REASSERT_S
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
                restored = self._restore(part, want["intent"])
                calls = calls + restored
                entry["calls"] = calls
                # An inverter that forgets what it was told (Victron) or whose timer only starts over on a write (Solis,
                # SolarEdge) gets every value written each time - not only the changed ones, or an unchanged one (the
                # maximum charge power while the power follows the slot) is never written again and goes stale.
                force = self._forced(prof) and self.is_battery(part)
                if self.is_battery(part):
                    async with self._lock():
                        entry["result"] = await self._send_kept(prof, calls, force)
                else:
                    entry["result"] = await self._send(calls)
                if entry["result"] != "ok":  # what failed, for the developer's view of the brand (setupinfo.py)
                    errs = getattr(self, "part_errors", None)
                    if errs is None:
                        errs = self.part_errors = {}
                    entry["error"] = getattr(self, "last_send_error", None)
                    msg = f"{want['intent']}: {getattr(self, 'last_send_error', None) or entry['result']}"[:200]
                    if msg not in errs.setdefault(part, []):
                        errs[part] = (errs[part] + [msg])[-3:]
                if not changed:
                    self._note_resent(part, "due")
                if entry["result"] == "ok" and want["intent"] != "export" and self.is_battery(part):
                    back = {c["data"].get("entity_id") for c in calls[len(calls) - len(restored):]} if restored else set()
                    left = {e: v for e, v in (self.ov.settings.get("restore_values") or {}).items() if e not in back}
                    if left != (self.ov.settings.get("restore_values") or {}):
                        self.ov.save({"restore_values": left})
            elif mode == "control":
                entry["blocked"] = self.blocked(part)
            self.last[part] = entry
            if changed:
                self.log.setdefault(part, deque(maxlen=60)).appendleft(entry)
        try:
            self._observe()
        except Exception:  # noqa: BLE001 - only watching, never in the way
            _LOGGER.debug("Observing failed", exc_info=True)

    def _observe(self) -> None:
        """Daily control as a test: when the battery has done what it was told for a while (the same checks as the
        self-test), that order counts as working for this profile - once a day each. Only watches; sends nothing."""
        from .selftest import _expect

        part = "battery"
        entry = self.last.get(part) or {}
        if self.mode(part) != "control" or self.blocked(part) or entry.get("result") != "ok" or part in getattr(self, "testing", set()):
            self._obs = {}
            return
        intent, f = entry.get("intent"), self.ov.flow() or {}
        ctx = entry.get("ctx") or {}
        if intent == "charge" and (f.get("soc") or 0) >= float(ctx.get("target") or 100) - 2:
            return  # full enough: charging can't be seen
        obs = getattr(self, "_obs", {}) or {}
        if obs.get("intent") != intent:
            obs = {"intent": intent, "since": time.time(), "ok": 0}
        if time.time() - obs["since"] < 180:
            self._obs = obs
            return  # give it time to react
        good = _expect(intent, f, {})
        obs["ok"] = obs["ok"] + 1 if good else 0 if good is False else obs["ok"]
        self._obs = obs
        if obs["ok"] < 3:
            return
        today = time.strftime("%Y-%m-%d")
        seen = dict(self.ov.settings.get("observed") or {})
        if seen.get(intent) == today:
            return
        seen[intent] = today
        self.ov.save({"observed": seen})
        tel = getattr(self.ov, "telemetry", None)
        if tel:
            tel.event("observed", {"profile": self.profile_key(part), "model": getattr(self, "model", None), "intent": intent})

    def _battery_volt(self) -> float:
        """The battery's voltage: the BMS voltage on the battery level sensor, a battery voltage sensor, else 52 V."""
        states = self.ha.states
        try:
            soc = self.ov.roles().get("battery_soc")
        except Exception:  # noqa: BLE001
            soc = None
        for k in ("BMS Voltage", "bms_voltage", "voltage"):
            v = _num(((states.get(soc) or {}).get("attributes") or {}).get(k)) if soc else None
            if v and 40 <= v <= 1000:
                return v
        pre = soc.split(".", 1)[1].rsplit("_battery", 1)[0] if soc and "_battery" in soc else ""
        for e in sorted(states, key=lambda e: (pre not in e, e)):
            if re.fullmatch(r"sensor\..*battery_voltage", e):
                v = _num((states[e] or {}).get("state"))
                if v and 40 <= v <= 1000:
                    return v
        return 52.0

    def _restore(self, part: str, intent: str) -> list[dict[str, Any]]:
        """Settings that are the owner's own (Victron's grid setpoint, Deye's work mode when selling, Deye's grid charge
        current when charging): remembered before EP changes them, put back when that stops - kept on disk, so a
        restart in between doesn't lose them."""
        prof = (adapters.PROFILES.get(self.profile_key(part) or "") or {}) if self.is_battery(part) else {}
        by_intent = {"export": prof.get("restore") or [], "charge": prof.get("restore_charge") or []}
        pats = by_intent["export"] + by_intent["charge"]
        if not pats:
            return []
        pool = self._pool(part)
        saved = dict(self.ov.settings.get("restore_values") or {})
        keep = set()  # what EP sets now: remembered (once), not put back
        for p in by_intent.get(intent) or []:
            e = adapters._find(p, pool)
            if not e:
                continue
            keep.add(e)
            st = (self.ha.states.get(e) or {}).get("state")
            if e not in saved and st not in (None, "unknown", "unavailable"):
                saved[e] = "0" if _negative(e, st) else st  # a setpoint already selling is ours, not the owner's
        if saved != (self.ov.settings.get("restore_values") or {}):
            self.ov.save({"restore_values": saved})
        if intent == "export":
            return []
        mine = {e: v for e, v in saved.items() if e in pool and e not in keep}  # each inverter remembers its own
        pats = by_intent["export"]
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

    def _lock(self) -> asyncio.Lock:
        if getattr(self, "_bat_lock", None) is None:
            self._bat_lock = asyncio.Lock()
        return self._bat_lock

    def _fixed(self, part: str, intent: str, calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """An option the test found works on this installation is used instead of the profile's (see selftest.py);
        else one that 3 other installations with the same profile found (telemetry.py) - only when this inverter
        offers it, and never one the user undid."""
        fx = (((self.ov.settings.get("profile_fixes") or {}).get(part) or {}).get(intent)) or {}
        key = self.profile_key(part) if self.is_battery(part) else f"car:{self.platforms.get(part) or ''}"
        shared = [f for f in ((self.ov.settings.get("community") or {}).get("fixes") or [])
                  if f.get("profile") == key and f.get("intent") == intent
                  and f"{intent}|{f.get('from')}|{f.get('to')}" not in (self.ov.settings.get("community_ignore") or [])]
        if not fx and not shared:
            return calls
        out = []
        for c in calls:
            e = c["data"].get("entity_id")
            if c.get("service") == "select_option" and e in fx:
                c = {**c, "data": {**c["data"], "option": fx[e]["to"]}}
            elif c.get("service") == "select_option":
                opts = ((self.ha.states.get(e) or {}).get("attributes") or {}).get("options") or []
                hit = next((f for f in shared if f.get("from") == c["data"].get("option") and f.get("to") in opts
                            and safe_shared_fix(intent, str(f.get("from")), str(f.get("to")))), None)
                if hit:
                    c = {**c, "data": {**c["data"], "option": hit["to"]}}
                    self.__dict__.setdefault("community_used", {})[f"{intent}|{hit['from']}|{hit['to']}"] = {"intent": intent, "from": hit["from"], "to": hit["to"]}
            out.append(c)
        return out

    @staticmethod
    def _forced(prof: dict[str, Any]) -> bool:
        """Written again on time even when Home Assistant shows the value: the inverter forgets it (Victron) or a
        remote-control timer only starts over on a write (Solis, SolarEdge)."""
        return bool(prof.get("resets_itself") or prof.get("keepalive"))

    def _prof(self, part: str) -> dict[str, Any]:
        return (adapters.PROFILES.get(self.profile_key(part) or "") or {}) if self.is_battery(part) else {}

    def _note_resent(self, part: str, why: str) -> None:
        """The log lists changes only; a value sent again is counted on the change it repeats (seen in diagnostics)."""
        log = self.log.get(part)
        if log:
            log[0]["resent"] = int(log[0].get("resent", 0)) + 1
            log[0]["resent_last"] = {"t": time.time(), "why": why}

    async def keep(self) -> None:
        """Every minute, for inverters that forget what they were told (Victron, EcoFlow): the last values are sent
        again on time - not up to a round later - and at once when a control is back after being unavailable."""
        now_t = time.time()
        for part in ["battery", *self.bat_parts()]:
            if part in getattr(self, "testing", set()):
                continue
            prof = self._prof(part)
            prev = self.last.get(part)
            if (not prof.get("reassert_s") or not prev or prev.get("mode") != "control" or "result" not in prev
                    or self.mode(part) != "control" or self.blocked(part) or self._lock().locked()):
                continue
            ids = {c["data"].get("entity_id") for c in prev["calls"] if isinstance(c["data"].get("entity_id"), str)}
            state = {e: (self.ha.states.get(e) or {}).get("state") for e in ids}
            down = {e for e, v in state.items() if v == "unavailable"}
            # "unknown" isn't gone: Victron's integration shows it when the GX hasn't repeated the value for 5
            # minutes - writing it now brings it back.
            blank = {e for e, v in state.items() if v == "unknown"}
            back = self._gone.get(part, set()) - down
            self._gone[part] = (self._gone.get(part, set()) & ids) | down
            if down:
                continue  # nothing can be written while it's away
            why = "back" if back else "unknown" if blank else "due" if now_t - prev["t"] > prof["reassert_s"] else None
            if not why:
                continue
            self._gone[part] = set()
            if why == "back":
                _LOGGER.info("%s controls are back (%s) - set again", part, ", ".join(sorted(back)))
            async with self._lock():
                if why == "due":
                    prev["result"] = await self._send_kept(prof, prev["calls"], self._forced(prof))
                else:
                    prev["result"] = await self._send(prev["calls"], force=True)
            prev["t"] = time.time()
            self._note_resent(part, why)

    async def _send_kept(self, prof: dict[str, Any], calls: list[dict[str, Any]], force: bool) -> str:
        """Forced writes limited to the profile's "keepalive_only" (SolarEdge: the timer and the command) - the rest sits
        in the inverter's flash and is written only when it changed."""
        only = prof.get("keepalive_only")
        if not force or not only:
            return await self._send(calls, force=force)
        hit = lambda c: any(re.search(r, str((c.get("data") or {}).get("entity_id") or "")) for r in only)  # noqa: E731
        rest = await self._send([c for c in calls if not hit(c)])
        kept = await self._send([c for c in calls if hit(c)], force=True)
        return kept if rest == "ok" else rest

    async def _send(self, calls: list[dict[str, Any]], force: bool = False) -> str:
        """Send the calls - only those whose value isn't already set (some links, like Solarman, drop writes now
        and then, so fewer writes is safer), or all of them when forced. A value that didn't stick is sent once more."""
        todo = list(calls) if force else [c for c in calls if not self._matches(c)]
        self.last_send_error = None
        for attempt in range(2):
            raised = []
            for c in todo:
                try:
                    await self.ha.call_service(c["domain"], c["service"], dict(c["data"]))
                    await asyncio.sleep(1.5)  # inverters take one change at a time
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Control call %s.%s failed: %s", c["domain"], c["service"], err)
                    self.last_send_error = f"{c['domain']}.{c['service']}: {err}"[:300]
                    raised.append(c)
                    if attempt:
                        return f"failed: {c['domain']}.{c['service']}"
            if not todo:
                return "ok"
            await asyncio.sleep(15)
            # A call that raised is tried once more - a service can't be read back, so it would otherwise count as done.
            todo = [c for c in calls if self._matches(c) is False or c in raised]
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
    WRONG_S = 15 * 60  # the battery doing the opposite this long: back to normal …
    SAFE_S = 3600  # … for an hour, with a warning
    CAR_IDLE_S = 10 * 60  # told to charge, plugged in, nothing flows this long: stop and start once

    @staticmethod
    def _opposite(intent: str, f: dict[str, Any]) -> bool:
        """Clearly the opposite of what it was told - not just slower (a full battery, a taper, the house's use)."""
        b = f.get("battery")
        if b is None:
            return False
        if intent == "charge":
            return b < -300
        if intent == "export":
            return b > 300 and (f.get("grid") or 0) > 300
        if intent == "hold":
            return b < -800
        return False

    async def guard(self) -> None:
        """Every minute while Energy Pilot controls: a battery doing the opposite of what it was told goes back to
        normal (the safe way) and the user is told; a charger that doesn't start is stopped and started once."""
        now_t = time.time()
        f = self.ov.flow()
        prev = self.last.get("battery")
        if (self.mode("battery") == "control" and "battery" not in self.testing and prev and prev.get("result") == "ok"
                and not self.blocked("battery") and not self.bat_parts() and now_t >= self.safe_until.get("battery", 0)):
            if self._opposite(prev["intent"], f):
                since = self._wrong.setdefault("battery", now_t)
                if now_t - since >= self.WRONG_S and now_t - prev["t"] >= self.WRONG_S:
                    _LOGGER.warning("The battery did the opposite of %s for %d min - back to normal for an hour", prev["intent"], self.WRONG_S // 60)
                    self.safe_until["battery"] = now_t + self.SAFE_S
                    self.safe_why = prev["intent"]
                    self._wrong.pop("battery", None)
                    self.last.pop("battery", None)
                    await self.tick(("battery",))
            else:
                self._wrong.pop("battery", None)
        else:
            self._wrong.pop("battery", None)
        # The charger: told to charge, the car in, nothing flowing.
        prev = self.last.get("car")
        if not f.get("plug"):
            self._car_idle.pop("car", None)
            self._kicked.pop("car", None)
            self.car_stuck.pop("car", None)
            return
        if (self.mode("car") != "control" or "car" in self.testing or not prev or prev.get("intent") != "charge"
                or prev.get("result") != "ok" or (f.get("ev") or 0) >= 100):
            self._car_idle.pop("car", None)
            if (f.get("ev") or 0) >= 100:
                self.car_stuck.pop("car", None)
            return
        since = self._car_idle.setdefault("car", now_t)
        if now_t - since < self.CAR_IDLE_S or now_t - prev["t"] < self.CAR_IDLE_S:
            return
        if not self._kicked.get("car"):
            _LOGGER.info("The car is in and told to charge, but nothing flows - stopping and starting the charger once")
            self._kicked["car"] = True
            await self._send(self.calls("car", {"intent": "stop", "ctx": prev.get("ctx") or {"current": 6}}), force=True)
            await asyncio.sleep(30)
            self.last.pop("car", None)
            self._car_idle.pop("car", None)
            await self.tick(("car",))
        else:
            self.car_stuck["car"] = True  # shown as a note: the car may be full or wait for its own timer

    async def recheck(self) -> None:
        """Every minute: a battery value that held and then changed by itself (the inverter left its slot) is found
        within a minute, not at the next round - the round then sets it again (see tick)."""
        prev = self.last.get("battery")
        if (not prev or prev.get("result") != "ok" or self.mode("battery") != "control" or self.blocked("battery")
                or "battery" in getattr(self, "testing", set()) or time.time() - prev["t"] < 60 or self._lock().locked()):
            return
        if any(self._matches(c) is False for c in prev.get("calls") or []):
            await self.tick(("battery",))

    def _dst_note(self) -> dict[str, Any] | None:
        """A week after the clocks change, where they do: an inverter steered by time slots keeps its own clock, and
        many don't move it by themselves - the slots are then an hour off. Only shown where summer time exists."""
        prof = adapters.PROFILES.get(self.profile_key("battery") or "") or {}
        if not any("{lease_" in str(v) or "{now_from}" in str(v) for i in ("charge", "export") for v in prof.get(i, [])):
            return None
        try:
            tz = ZoneInfo(self.ha.config.get("time_zone") or "UTC")
        except Exception:  # noqa: BLE001
            return None
        now = datetime.now(tz)
        for days in range(0, 8):
            d = now - timedelta(days=days)
            before = (d - timedelta(days=1)).utcoffset()
            if before is not None and d.utcoffset() != before:
                return {"key": "clock_dst", "level": "info", "vals": {"date": d.date().isoformat()}, "goto": "battery"}
        return None

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
        if now_t < getattr(self, "safe_until", {}).get("battery", 0):
            out.append({"key": "acting_wrong", "level": "warn", "vals": {"intent": getattr(self, "safe_why", "")}, "goto": "battery"})
        if getattr(self, "car_stuck", {}).get("car"):
            out.append({"key": "charger_stuck", "level": "info", "vals": {}, "goto": "car"})
        pm = str((self.ha.states.get("select.predbat_mode") or {}).get("state") or "")
        if self.mode("battery") == "control" and pm and pm.lower() not in ("monitor", "unavailable", "unknown"):
            out.append({"key": "predbat_on", "level": "warn", "vals": {"mode": pm}, "goto": "battery"})
        if self.mode("battery") == "control" and (note := self._dst_note()):
            out.append(note)
        return out

    def _took(self, calls: list[dict[str, Any]]) -> bool:
        """Did the controls take the values? (Selects and numbers that can be read back.)"""
        return all(self._matches(c) is not False for c in calls)

    async def let_go(self, budget_s: float = 12.0) -> None:
        """Energy Pilot is stopping (an update, a restart, the app turned off): every battery it controls is put back
        to normal, so no order is left standing while it's away. The modes are kept - it takes over again when it's
        back. Quick: no read-back, at most `budget_s` seconds (the Supervisor kills the app soon after asking)."""
        wants = self.intents()
        calls = []
        for part in ["battery", *self.bat_parts()]:
            if self.mode(part) == "control" and not self.blocked(part) and (want := wants.get(part)):
                calls += self.calls(part, {**want, "intent": "normal"}) + self._restore(part, "normal")
        todo = [c for c in calls if not self._matches(c)]
        end = time.time() + budget_s
        for c in todo:
            if time.time() > end:
                _LOGGER.warning("Stopping: not every control was put back to normal in time")
                return
            try:
                await asyncio.wait_for(self.ha.call_service(c["domain"], c["service"], dict(c["data"])), timeout=max(0.5, end - time.time()))
            except Exception as err:  # noqa: BLE001 - try the rest
                _LOGGER.info("Stopping: %s.%s not sent: %s", c["domain"], c["service"], err)
        if todo:
            _LOGGER.info("Stopping: the battery is back to normal (%d changes)", len(todo))

    async def release(self) -> None:
        """Back to shadow: the battery is put back to normal first. A charger is left as it is - unless it has its own
        planning (evcc), which it gets back."""
        wants = self.intents()
        for part in ["battery", *self.bat_parts()]:
            if self.mode(part) == "control" and not self.blocked(part) and (want := wants.get(part)):
                await self._send(self.calls(part, {**want, "intent": "normal"}) + self._restore(part, "normal"))
        for part in ["car", *self.car_parts()]:
            if self.mode(part) == "control" and not self.blocked(part) and (calls := self._charger_hand_back(part)):
                await self._send(self._clamp(calls))
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
                          "model": self.model, "tested": bool(prof.get("tested")) if key != "custom" else None, "check": self.check(),
                          # how many other installations with this profile have run the self-test (telemetry.py)
                          "community": ((self.ov.settings.get("community") or {}).get("tested") or {}).get(key or "")}
        # For "Chosen by you": every control in Home Assistant - the inverter's own first - not only the device
        # the battery level was found on (that could be the wrong one, e.g. a car).
        own = set(self.entities["battery"])
        everything = [e for e in self.ha.states if e.split(".")[0] in ("select", "number", "switch", "button", "time", "script")]
        out["profile"]["all_controls"] = sorted(own) + sorted(e for e in everything if e not in own)
        return out


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _negative(entity: str, value: Any) -> bool:
    """A grid setpoint below 0: the inverter sells to the grid."""
    if not entity.startswith("number.") or not re.search(r"grid_set_?point|acpowersetpoint", entity):
        return False
    try:
        return float(value) < 0
    except (TypeError, ValueError):
        return False

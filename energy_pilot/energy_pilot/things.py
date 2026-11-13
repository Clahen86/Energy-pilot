"""Things that run cheaply: small batteries (a robot mower, an e-bike, tool batteries) and machines (washing machine,
dryer, dishwasher) - run on the sun or in the cheapest hours.

They come after what matters most: the house battery and the car are planned first, and a thing only gets the sun
that is left over (what the plan would sell) or cheap hours that keep within the main fuse with the cars charging.

A battery sits on a switch (a Shelly, a smart plug): Energy Pilot switches it on in its hours and off again; when the
charger stops drawing power the battery is full - done for the day. A machine is never switched off: once the user has
said it is ready, Energy Pilot only starts it (a remote start button or switch), or tells the user when to press start.
How much each thing takes and how long is learned from the runs seen (the median of the last ten, from three runs).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from statistics import median
from typing import Any

MODES = ("sun_cheap", "sun", "cheap")
RUN_W = 15  # a machine above this draws power: it runs
IDLE_W = 5  # below this it rests
MACHINE_END_S = 15 * 60  # a machine resting this long has finished (a dishwasher drying can rest a few minutes)
FULL_S = 10 * 60  # a battery charger resting this long while on: the battery is full


def _hhmm(text: str | None, now: datetime) -> datetime | None:
    """The next time it is HH:MM (today or tomorrow)."""
    if not text:
        return None
    try:
        hh, mm = (int(x) for x in str(text).split(":")[:2])
    except ValueError:
        return None
    t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return t if t > now else t + timedelta(days=1)


def _num(state: dict[str, Any] | None) -> float | None:
    """A power sensor's value in W."""
    if not state:
        return None
    try:
        v = float(state.get("state"))
    except (TypeError, ValueError):
        return None
    return v * 1000 if str((state.get("attributes") or {}).get("unit_of_measurement") or "").lower() == "kw" else v


class Things:
    def __init__(self, state: dict[str, Any]) -> None:
        self.s = state.setdefault("things", {})
        self.plans: dict[str, dict[str, Any]] = {}
        self._sent: dict[str, datetime] = {}

    def st(self, tid: str) -> dict[str, Any]:
        return self.s.setdefault(tid, {"runs": []})

    @staticmethod
    def items(settings: dict[str, Any]) -> list[dict[str, Any]]:
        return [t for t in (settings.get("things") or []) if isinstance(t, dict) and t.get("id")]

    # ---------- what a thing takes ----------

    def learned(self, tid: str) -> dict[str, Any] | None:
        runs = (self.st(tid).get("runs") or [])[-10:]
        if len(runs) < 3:
            return None
        return {"kwh": round(median(r["kwh"] for r in runs), 2), "min": round(median(r["min"] for r in runs)), "n": len(self.st(tid)["runs"])}

    def need(self, t: dict[str, Any]) -> tuple[float, float, float]:
        """(kWh, minutes, kW) one run takes: learned, else the settings, else a fair guess."""
        lr = self.learned(t["id"])
        battery = t.get("kind") != "machine"
        kwh = lr["kwh"] if lr else float(t.get("kwh") or (0.5 if battery else 1.0))
        if lr and lr["min"] > 0:
            minutes = float(lr["min"])
        elif t.get("kw"):
            minutes = kwh / float(t["kw"]) * 60
        else:
            minutes = 240.0 if battery else 120.0
        minutes = max(10.0, minutes)
        return kwh, minutes, max(0.02, kwh / (minutes / 60))

    # ---------- the plan ----------

    def plan(self, settings: dict[str, Any], hours: list[Any], now: datetime, left: dict[datetime, float],
             load: dict[datetime, float], limit: float | None) -> list[dict[str, Any]]:
        """Each thing's hours (a battery) or start (a machine). left: the sun left over per slot (kWh) after the house,
        the battery and the cars; load: what the cars draw per slot (kW), for the main fuse."""
        out = []
        self.plans = {}
        for t in self.items(settings):
            tid, s = t["id"], self.st(t["id"])
            kwh, minutes, kw = self.need(t)
            mode = t.get("mode") if t.get("mode") in MODES else "sun_cheap"
            until = _hhmm(t.get("ready"), now) or now + timedelta(hours=24)
            ok = [h for h in hours if h.start + timedelta(hours=h.length) > now and h.start < until
                  and (limit is None or h.house / h.length + load.get(h.start, 0.0) + kw <= limit + 1e-9)]

            def sunny(h: Any) -> bool:
                return left.get(h.start, 0.0) >= kw * h.length * 0.7

            def cost(h: Any) -> float:
                return h.sell if mode != "cheap" and sunny(h) else h.price

            p: dict[str, Any] = {"id": tid, "hours": [], "start": None, "sun": False}
            if t.get("kind") == "machine":
                if s.get("armed") and not s.get("running") and not s.get("start_sent"):
                    p.update(self._machine_start(ok, now, until, minutes, kw, mode, sunny, cost))
            elif not self.full_today(tid, now):
                rest = max(0.0, kwh - float(s.get("kwh_now") or 0))
                use = [h for h in ok if mode != "sun" or sunny(h)]
                chosen, got = [], 0.0
                for h in sorted(use, key=lambda h: (cost(h), h.start)):
                    if got >= rest:
                        break
                    chosen.append(h)
                    got += kw * h.length
                p["hours"] = sorted(h.start.isoformat() for h in chosen)
                p["sun"] = bool(chosen) and all(sunny(h) for h in chosen)
                p["slot_h"] = chosen[0].length if chosen else None
            self.plans[tid] = p
            out.append(p)
        return out

    @staticmethod
    def _machine_start(ok: list[Any], now: datetime, until: datetime, minutes: float, kw: float, mode: str,
                       sunny: Any, cost: Any) -> dict[str, Any]:
        """The start that costs least for the whole run, finished by the time it must be ready."""
        run = timedelta(minutes=minutes)
        starts = sorted({max(now, h.start) for h in ok if max(now, h.start) + run <= until + timedelta(minutes=1)})
        best = None
        for s0 in starts:
            end, total, sun_all = s0 + run, 0.0, True
            for h in ok:
                a, b = max(s0, h.start), min(end, h.start + timedelta(hours=h.length))
                if b > a:
                    total += kw * (b - a).total_seconds() / 3600 * cost(h)
                    sun_all = sun_all and sunny(h)
            covered = sum(max(0.0, (min(end, h.start + timedelta(hours=h.length)) - max(s0, h.start)).total_seconds()) for h in ok)
            if covered < run.total_seconds() * 0.95 or (mode == "sun" and not sun_all):
                continue
            if best is None or total < best[0] - 1e-6:
                best = (total, s0, sun_all)
        if best is None:
            return {}
        return {"start": best[1].isoformat(), "sun": best[2], "cost": round(best[0], 2)}

    def full_today(self, tid: str, now: datetime) -> bool:
        done = self.st(tid).get("done")
        return bool(done) and datetime.fromisoformat(done).date() == now.date()

    # ---------- running them ----------

    async def tick(self, ha: Any, settings: dict[str, Any], now: datetime, price: float | None, sell: float,
                   grid_w: float | None, dt_s: float = 30) -> None:
        """Every half minute: switch the batteries, start the machines, measure what they use."""
        for t in self.items(settings):
            try:
                if t.get("kind") == "machine":
                    await self._tick_machine(ha, t, now, price, sell, grid_w, dt_s)
                else:
                    await self._tick_battery(ha, t, now, price, sell, grid_w, dt_s)
            except Exception:  # noqa: BLE001 - one thing must never stop the others
                import logging

                logging.getLogger("energy_pilot.things").debug("Thing %s failed", t.get("id"), exc_info=True)

    @staticmethod
    def _price_now(price: float | None, sell: float, grid_w: float | None) -> float:
        return sell if grid_w is not None and grid_w < 0 else (price or 0.0)  # selling now: the sun pays for it

    def _measure(self, s: dict[str, Any], w: float, now: datetime, price: float, dt_s: float) -> None:
        kwh = w / 1000 * dt_s / 3600
        s["kwh_now"] = round(float(s.get("kwh_now") or 0) + kwh, 5)
        s["cost_now"] = round(float(s.get("cost_now") or 0) + kwh * price, 5)
        s["min_now"] = round(float(s.get("min_now") or 0) + dt_s / 60, 2)

    def _finish(self, s: dict[str, Any], now: datetime) -> None:
        if float(s.get("kwh_now") or 0) >= 0.01 and float(s.get("min_now") or 0) >= 5:
            s["runs"] = (s.get("runs") or [])[-19:] + [{"kwh": round(s["kwh_now"], 3), "min": round(s["min_now"])}]
        s["last"] = {"end": now.isoformat(), "kwh": round(float(s.get("kwh_now") or 0), 2), "cost": round(float(s.get("cost_now") or 0), 2)}
        s["kwh_now"], s["cost_now"], s["min_now"], s["quiet_since"] = 0.0, 0.0, 0.0, None

    def _in_hours(self, tid: str, now: datetime) -> bool:
        p = self.plans.get(tid) or {}
        length = timedelta(hours=p.get("slot_h") or 1)
        return any(datetime.fromisoformat(x) <= now < datetime.fromisoformat(x) + length for x in p.get("hours") or [])

    async def _switch(self, ha: Any, entity: str, on: bool, now: datetime) -> None:
        state = (ha.states.get(entity) or {}).get("state")
        if state == ("on" if on else "off"):
            return
        last = self._sent.get(entity)
        if last and (now - last).total_seconds() < 120:
            return  # it was just told: give it time
        self._sent[entity] = now
        await ha.call_service("homeassistant", "turn_on" if on else "turn_off", {"entity_id": entity})

    async def _tick_battery(self, ha: Any, t: dict[str, Any], now: datetime, price: float | None, sell: float,
                            grid_w: float | None, dt_s: float) -> None:
        tid, s, sw = t["id"], self.st(t["id"]), t.get("switch")
        if not sw:
            return
        if s.get("done") and not self.full_today(tid, now):
            s["done"] = None  # a new day: charge again
        on = (ha.states.get(sw) or {}).get("state") == "on"
        w = _num(ha.states.get(t["power"])) if t.get("power") else None
        _, minutes, kw = self.need(t)
        if on:
            self._measure(s, w if w is not None else kw * 1000, now, self._price_now(price, sell, grid_w), dt_s)
        want = self._in_hours(tid, now) and not self.full_today(tid, now)
        if on and w is not None and float(s.get("min_now") or 0) >= 5:
            if w < IDLE_W:  # on, but the charger takes nothing: full (or the battery is not on it)
                s["quiet_since"] = s.get("quiet_since") or now.isoformat()
                if (now - datetime.fromisoformat(s["quiet_since"])).total_seconds() >= FULL_S:
                    s["done"] = now.isoformat()
                    self._finish(s, now)
                    want = False
            else:
                s["quiet_since"] = None
        elif on and w is None and float(s.get("min_now") or 0) >= minutes:
            s["done"] = now.isoformat()  # no power sensor: charged for as long as it takes
            self._finish(s, now)
            want = False
        await self._switch(ha, sw, want, now)

    async def _tick_machine(self, ha: Any, t: dict[str, Any], now: datetime, price: float | None, sell: float,
                            grid_w: float | None, dt_s: float) -> None:
        """A machine is never switched off: only started when it is ready and the time has come."""
        tid, s = t["id"], self.st(t["id"])
        w = _num(ha.states.get(t["power"])) if t.get("power") else None
        p = self.plans.get(tid) or {}
        if s.get("armed") and not s.get("running") and not s.get("start_sent") and p.get("start") \
                and datetime.fromisoformat(p["start"]) <= now:
            s["start_sent"] = now.isoformat()
            if st := t.get("start"):
                domain = st.split(".")[0]
                if domain == "button":
                    await ha.call_service("button", "press", {"entity_id": st})
                elif domain in ("switch", "input_boolean"):
                    await ha.call_service(domain, "turn_on", {"entity_id": st})
            else:
                await ha.call_service("persistent_notification", "create", {
                    "notification_id": f"energy_pilot_{tid}", "title": "Energy Pilot",
                    "message": f"▶ {t.get('name') or 'Machine'}: start it now."})
        _, minutes, kw = self.need(t)
        running_now = (w is not None and w > RUN_W) or (w is None and s.get("start_sent") is not None)
        if running_now and not s.get("running"):
            s["running"], s["started"] = True, now.isoformat()
        if s.get("running"):
            self._measure(s, w if w is not None else kw * 1000, now, self._price_now(price, sell, grid_w), dt_s)
            ended = False
            if w is not None:
                if w < IDLE_W:
                    s["quiet_since"] = s.get("quiet_since") or now.isoformat()
                    ended = (now - datetime.fromisoformat(s["quiet_since"])).total_seconds() >= MACHINE_END_S
                else:
                    s["quiet_since"] = None
            else:
                ended = float(s.get("min_now") or 0) >= minutes
            if ended:
                if w is not None:  # the resting minutes at the end are not part of the run
                    s["min_now"] = max(0.0, float(s.get("min_now") or 0) - MACHINE_END_S / 60)
                self._finish(s, now)
                s["running"], s["armed"], s["start_sent"], s["started"] = False, False, None, None
        elif s.get("start_sent") and w is not None:
            sent = datetime.fromisoformat(s["start_sent"])
            if (now - sent).total_seconds() > 30 * 60 and not t.get("start"):
                pass  # told the user; still waiting for them to press start - keep waiting
            elif (now - sent).total_seconds() > 10 * 60 and t.get("start"):
                s["start_sent"] = None  # the start didn't take (door open, remote start off): try again next round

    def arm(self, tid: str, armed: bool) -> None:
        s = self.st(tid)
        s["armed"] = bool(armed)
        if not armed:
            s["start_sent"] = None

    # ---------- for the page ----------

    def view(self, settings: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
        out = []
        for t in self.items(settings):
            tid, s = t["id"], self.st(t["id"])
            p = self.plans.get(tid) or {}
            kwh, minutes, _ = self.need(t)
            if t.get("kind") == "machine":
                status = "running" if s.get("running") else "waiting_start" if s.get("start_sent") else \
                    "planned" if s.get("armed") and p.get("start") else "armed" if s.get("armed") else \
                    "done" if s.get("last") and datetime.fromisoformat(s["last"]["end"]).date() == now.date() else "idle"
            else:
                on = bool(self._in_hours(tid, now))
                status = "full" if self.full_today(tid, now) else "charging" if on else "planned" if p.get("hours") else "idle"
            out.append({"id": tid, "name": t.get("name") or "", "icon": t.get("icon") or "", "kind": t.get("kind") or "battery",
                        "status": status, "hours": p.get("hours") or [], "start": p.get("start"), "sun": p.get("sun", False),
                        "slot_h": p.get("slot_h"), "kwh_now": round(float(s.get("kwh_now") or 0), 2), "need_kwh": round(kwh, 2),
                        "minutes": round(minutes), "learned": self.learned(tid), "last": s.get("last"),
                        "done_at": s.get("done"), "armed": bool(s.get("armed"))})
        return out


# ---------- finding them ----------

MACHINE_WORDS = re.compile(r"wash|vaske|vask_|dish|opvask|geschirr|spuel|spül|dryer|tørre|toerre|tumble|trockner|lave.?linge|"
                           r"lave.?vaisselle|seche|sèche|vaatwas|wasmachine|droger|tvatt|tvätt|disk|tork|oppvask", re.I)
BATTERY_WORDS = re.compile(r"mower|plæne|plaene|automower|rasenm|tondeuse|maaier|grasklipp|gräsklipp|gressklipp|e.?bike|"
                           r"elcykel|cykel|bike|fahrrad|velo|vélo|fiets|sykkel|tool|værktøj|vaerktoej|werkzeug|outil|gereedschap|verktyg", re.I)
NOT_THING = re.compile(r"phone|iphone|pixel|galaxy|ipad|tablet|laptop|macbook|watch|_tv|tv_|television|heat.?pump|varmepumpe|"
                       r"light|lys|lamp|inverter|growatt|battery_soc|ev_|charger|wallbox|keba|easee|zappi|car_", re.I)


def icon_for(text: str) -> str:
    t = text.lower()
    for key, words in (("dish", r"dish|opvask|geschirr|vaisselle|vaatwas|disk|oppvask|spül|spuel"),
                       ("dryer", r"dryer|tørre|toerre|tumble|trockner|seche|sèche|droger|tork"),
                       ("wash", r"wash|vask|linge|wasmachine|tvatt|tvätt"),
                       ("mower", r"mower|plæne|plaene|rasenm|tondeuse|maaier|klipp"),
                       ("bike", r"bike|cykel|fahrrad|velo|vélo|fiets|sykkel"),
                       ("tool", r"tool|værktøj|vaerktoej|werkzeug|outil|gereedschap|verktyg")):
        if re.search(words, t):
            return key
    return "plug"


def find(registry: list[dict[str, Any]], devices: dict[str, dict[str, Any]], states: dict[str, Any],
         taken: set[str], dismissed: list[str]) -> list[dict[str, Any]]:
    """Machines and small batteries in Home Assistant worth offering - only what clearly is one: a machine that can be
    started or measured, a mower or bike battery on a switch. Never phones, lights, the car or the house battery."""
    by_dev: dict[str, list[dict[str, Any]]] = {}
    for e in registry:
        if e.get("disabled_by") or e.get("platform") == "mobile_app" or e["entity_id"] not in states or not e.get("device_id"):
            continue
        by_dev.setdefault(e["device_id"], []).append(e)
    out = []
    for dev, ents in by_dev.items():
        if dev in dismissed:
            continue
        d = devices.get(dev) or {}
        dname = str(d.get("name_by_user") or d.get("name") or "")
        text = " ".join([dname, str(d.get("model") or ""), str(d.get("manufacturer") or "")]
                        + [e["entity_id"] for e in ents]).lower().replace(" ", "_")
        if NOT_THING.search(dname.lower().replace(" ", "_")):
            continue
        ids = [e["entity_id"] for e in ents]
        if any(i in taken for i in ids):
            continue
        power = next((i for i in ids if i.startswith("sensor.") and (states[i].get("attributes") or {}).get("device_class") == "power"), None)
        switch = next((i for i in ids if i.startswith("switch.") and not re.search(r"child|lock|led|light|lys|sound|beep", i)), None)
        start = next((i for i in ids if i.startswith("button.") and re.search(r"start", i)), None) or \
            next((i for i in ids if i.startswith("switch.") and re.search(r"remote_start|start", i)), None)
        if MACHINE_WORDS.search(text) and (start or power):
            out.append({"device": dev, "kind": "machine", "name": dname or ids[0], "icon": icon_for(text), "start": start, "power": power,
                        "remote": bool(start)})
        elif BATTERY_WORDS.search(text) and switch:
            out.append({"device": dev, "kind": "battery", "name": dname or ids[0], "icon": icon_for(text), "switch": switch, "power": power})
    return sorted(out, key=lambda c: (c["kind"] != "machine", c["name"].lower()))

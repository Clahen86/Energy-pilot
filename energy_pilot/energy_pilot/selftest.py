"""Test your system: Energy Pilot tries each thing it can tell the battery and the charger to do, watches whether it
really happens, mends what it can by itself, and puts everything back as it was.

Safe by design:
- Only the controls the brand's profile uses are touched - the same ones Energy Pilot controls anyway.
- At most 1 kW, a couple of minutes per step, and only when the user presses the button. A stop button puts it all
  back at once.
- Before the test every control's value is saved - on disk, so a restart in the middle still puts them back.
- A step only passes when the battery has done the right thing for 30 seconds in a row, after at least a minute.
- When a step fails, the control's other options are tried one at a time (never off-grid, calibration, factory …).
  One that works is kept for this installation and shown, and the user can undo it.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any
from urllib.parse import quote

_LOGGER = logging.getLogger(__name__)

REPO = "https://github.com/Clahen86/Energy-pilot/issues/new"
TEST_W = 1000  # at most this much power during a test
SAMPLE_S = 10  # how often the battery is looked at
STEADY_S = 30  # right this long in a row …
MIN_S = 60  # … and never sooner than this after a command
WAIT_S = {"local": 120, "cloud": 600, "car": 180}  # a cloud (AlphaESS, Tesla, EcoFlow) can take several minutes
CLOUD = {"alphaess", "tesla", "ecoflow"}
MAX_TRIES = 5  # other options tried for one step
# Options never tried: they could take the house off the grid, wipe settings or stop the inverter.
UNSAFE = re.compile(r"off.?grid|island|\beps\b|backup|calibrat|factory|reset|emergenc|maint|\btest|update|firmware|"
                    r"shut.?down|power.?off|standby|forbid|disable|\boff\b|sleep|debug|service", re.I)


def _norm(x: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(x).lower())


def _expect(intent: str, f: dict[str, Any], base: dict[str, Any]) -> bool | None:
    """Is the battery doing what the step asked for? None: there is nothing to tell by."""
    b, g = f.get("battery"), f.get("grid")
    if b is None:
        return None
    if intent == "charge":
        return b >= 300
    if intent == "hold":
        return b >= -150  # not discharging (the sun may still charge it)
    if intent == "export":
        return b <= -300 and (g is None or g <= -100)
    # normal: the battery covers the house again - not charging from the grid, not selling
    return not (b > 300 and (g or 0) > 300) and not (b < -300 and (g or 0) < -300)


def _expect_car(step: str, f: dict[str, Any], base: dict[str, Any]) -> bool | None:
    ev = f.get("ev")
    if ev is None:
        return None
    if step == "start":
        return ev >= 1000
    if step == "low":
        return ev >= 500 and ev <= (base.get("ev_high") or 99999) * 0.75
    return ev < 200  # stop


class SelfTest:
    def __init__(self, controller: Any, overview: Any) -> None:
        self.ctl, self.ov = controller, overview
        self._task: asyncio.Task | None = None
        self._stop = False

    # ---------- what the page shows ----------
    @property
    def state(self) -> dict[str, Any]:
        return self.ov.settings.get("selftest") or {}

    def _save(self, **kw: Any) -> None:
        self.ov.save({"selftest": {**self.state, **kw}})

    def status(self) -> dict[str, Any]:
        s = dict(self.state)
        s.pop("saved", None)
        s["running"] = bool(self._task and not self._task.done())
        s["can"] = self.can()
        s["fixes"] = self.fixes_list()
        s["report_url"] = self.report_url() if s.get("results") else None
        return s

    def can(self) -> dict[str, Any]:
        """What can be tested now - and why not."""
        f = self.ov.flow()
        out: dict[str, Any] = {}
        if self.ctl.profile_steps("battery") and (f.get("has") or {}).get("battery"):
            out["battery"] = None if f.get("battery") is not None else "no_power"
        else:
            out["battery"] = "no_battery"
        if self.ctl.entities.get("car") or self.ctl.platforms.get("car"):
            out["car"] = None if f.get("plug") else "not_plugged"
        else:
            out["car"] = "no_charger"
        return out

    def fixes_list(self) -> list[dict[str, Any]]:
        fx = self.ov.settings.get("profile_fixes") or {}
        return [{"part": p, "intent": i, "entity": e, **v} for p, by in fx.items() for i, ents in by.items() for e, v in ents.items()]

    # ---------- start / stop ----------
    def start(self, parts: list[str]) -> bool:
        if self._task and not self._task.done():
            return False
        can = self.can()
        parts = [p for p in parts if p in ("battery", "car") and can.get(p) is None]
        if not parts:
            return False
        self._stop = False
        self._save(parts=parts, results=[], step=None, started=time.time(), finished=None, restored=None, stopped=False)
        self._task = asyncio.create_task(self._run(parts))
        return True

    def stop(self) -> None:
        self._stop = True

    def undo(self, part: str, intent: str, entity: str) -> None:
        fx = dict(self.ov.settings.get("profile_fixes") or {})
        fx.get(part, {}).get(intent, {}).pop(entity, None)
        self.ov.save({"profile_fixes": fx})
        self.ctl.last.pop(part, None)

    async def recover(self) -> None:
        """After a restart in the middle of a test: put the saved values back."""
        if self.state.get("saved") and not self.state.get("restored"):
            _LOGGER.info("A test was cut short - putting the saved settings back")
            await self._restore()

    # ---------- the test ----------
    async def _run(self, parts: list[str]) -> None:
        self.ctl.testing = set(parts)
        try:
            snap = self._snapshot(parts)
            self._mem = snap  # kept here too: put back even if the file can't hold it
            self._save(saved=snap)
            if snap and self.state.get("saved") != snap:
                raise RuntimeError("the saved settings could not be stored - nothing is tried")
            if "battery" in parts:
                await self._battery()
            if "car" in parts and not self._stop:
                await self._car()
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Test failed", exc_info=True)
            self._result("error", "error", "failed", note="error")
        finally:
            await self._restore()
            self.ctl.testing = set()
            for p in parts:
                self.ctl.last.pop(p, None)  # the plan takes over again at once
            self._save(step=None, finished=time.time(), stopped=self._stop)
            tel = getattr(self.ov, "telemetry", None)
            if tel and not self._stop:
                tel.test_result(self.state.get("results") or [])

    def _result(self, part: str, step: str, result: str, **kw: Any) -> None:
        res = [r for r in self.state.get("results") or [] if not (r["part"] == part and r["step"] == step)]
        self._save(results=res + [{"part": part, "step": step, "result": result, **kw}])

    def _entities(self, part: str) -> list[str]:
        """Every control the profile (or the charger) could touch."""
        if part == "battery":
            steps = self.ctl.profile_steps("battery") or {}
            try:
                want = (self.ctl.intents().get("battery") or {"ctx": {}})["ctx"]
            except Exception:  # noqa: BLE001
                want = {}
            ids: set[str] = set()
            for intent, st in steps.items():
                if intent in ("normal", "hold", "charge", "export") and isinstance(st, list):
                    try:
                        from . import adapters
                        for c in adapters.resolve(st, self.ctl._pool("battery"), {**_ctx_defaults(), **want}):
                            e = (c.get("data") or {}).get("entity_id")
                            if isinstance(e, str):
                                ids.add(e)
                    except Exception:  # noqa: BLE001
                        continue
            return sorted(ids)
        return sorted(e for e in self.ctl.entities.get("car", []) if e.split(".")[0] in ("select", "number", "switch"))

    def _snapshot(self, parts: list[str]) -> dict[str, str]:
        out = {}
        for p in parts:
            for e in self._entities(p):
                st = self.ctl.ha.states.get(e) or {}
                v = st.get("state")
                if e.split(".")[0] in ("select", "number", "switch") and v not in (None, "unavailable", "unknown"):
                    out[e] = v
        return out

    async def _restore(self) -> None:
        saved = self.state.get("saved") or getattr(self, "_mem", None) or {}
        calls = []
        for e, v in saved.items():
            d = e.split(".")[0]
            if d == "select":
                calls.append({"domain": "select", "service": "select_option", "data": {"entity_id": e, "option": v}})
            elif d == "number":
                try:
                    n = float(v)
                except ValueError:
                    continue
                calls.append({"domain": "number", "service": "set_value", "data": {"entity_id": e, "value": int(n) if n.is_integer() else n}})
            elif d == "switch" and v in ("on", "off"):
                calls.append({"domain": "switch", "service": f"turn_{v}", "data": {"entity_id": e}})
        result = await self.ctl._send(calls) if calls else "ok"
        left = [c["data"]["entity_id"] for c in calls if self.ctl._matches(c) is False]
        self._mem = {}
        self._save(saved={}, restored={"result": result, "left": [{"entity": e, "value": saved[e]} for e in left]})

    async def _watch(self, check: Any, wait_s: int, base: dict[str, Any]) -> tuple[bool | None, dict[str, Any]]:
        """Look every 10 s; right for 30 s in a row and at least a minute after the command = passed."""
        t0, good_since, seen, last = time.time(), None, False, {}
        while time.time() - t0 < wait_s and not self._stop:
            await asyncio.sleep(SAMPLE_S)
            last = self.ov.flow()
            ok = check(last, base)
            if ok is None:
                good_since = None
                continue
            seen = True
            good_since = (good_since or time.time()) if ok else None
            if good_since and time.time() - good_since >= STEADY_S and time.time() - t0 >= MIN_S:
                return True, last
        return (False if seen else None), last

    async def _step(self, part: str, intent: str, calls: list[dict[str, Any]], check: Any, wait_s: int,
                    base: dict[str, Any]) -> None:
        self._save(step={"part": part, "step": intent, "since": time.time()})
        sent = await self.ctl._send(calls, force=True)
        ok, f = await self._watch(check, wait_s, base)
        if ok:
            self._result(part, intent, "ok")
            return
        if self._stop:
            return
        # Not right: try the control's other options, one at a time.
        for c, opt in self._alternatives(calls):
            if self._stop:
                return
            self._save(step={"part": part, "step": intent, "since": time.time(), "trying": {"entity": c["data"]["entity_id"], "option": opt}})
            tried = [x if x is not c else {**c, "data": {**c["data"], "option": opt}} for x in calls]
            await self.ctl._send(tried, force=True)
            ok, f = await self._watch(check, wait_s, base)
            if ok:
                e = c["data"]["entity_id"]
                fx = dict(self.ov.settings.get("profile_fixes") or {})
                fx.setdefault(part, {}).setdefault(intent, {})[e] = {"from": c["data"]["option"], "to": opt}
                self.ov.save({"profile_fixes": fx})
                self._result(part, intent, "fixed", entity=e, option_from=c["data"]["option"], option_to=opt)
                return
        why = "rejected" if sent != "ok" else ("no_reaction" if ok is False else "no_data")
        err = getattr(self.ctl, "last_send_error", None) if sent != "ok" else None
        if err and re.search(r"no existing period|create it in the alpha", err, re.I):
            why = "alpha_period"  # AlphaESS changes only a period that exists: one has to be made in its app first
        rejected = [{"entity": c["data"].get("entity_id"), "value": c["data"].get("option", c["data"].get("value"))}
                    for c in calls if self.ctl._matches(c) is False]
        self._result(part, intent, "failed", why=why, rejected=rejected, error=err,
                     seen={k: f.get(k) for k in ("battery", "grid", "ev") if f})

    def _alternatives(self, calls: list[dict[str, Any]]) -> list[tuple[dict[str, Any], str]]:
        """Other safe options for the selects in a step, the most alike first; at most a handful in all."""
        out = []
        for c in calls:
            if c.get("service") != "select_option":
                continue
            e, want = c["data"]["entity_id"], str(c["data"].get("option"))
            opts = ((self.ctl.ha.states.get(e) or {}).get("attributes") or {}).get("options") or []
            words = set(re.findall(r"[a-z]{3,}", want.lower()))
            cands = [o for o in opts if str(o) != want and not UNSAFE.search(str(o))]
            cands.sort(key=lambda o: -len(words & set(re.findall(r"[a-z]{3,}", str(o).lower()))))
            out += [(c, str(o)) for o in cands]
        return out[:MAX_TRIES]

    async def _battery(self) -> None:
        f = self.ov.flow()
        soc = f.get("soc")
        try:
            want = self.ctl.intents().get("battery") or {"ctx": {}}
        except Exception:  # noqa: BLE001 - no plan yet: the test still runs
            want = {"ctx": {}}
        ctx = {**_ctx_defaults(), **want["ctx"]}
        ctx = _limit(ctx, soc)
        steps = self.ctl.profile_steps("battery") or {}
        key = self.ctl.profile_key("battery") or ""
        wait_s = WAIT_S["cloud" if key in CLOUD else "local"]
        plan = ["hold", "charge"]
        if steps.get("export") and self.ov.settings.get("battery_export"):
            plan.append("export")
        plan.append("normal")
        base = {"battery": f.get("battery"), "grid": f.get("grid")}
        for intent in plan:
            if self._stop:
                return
            if intent == "charge" and soc is not None and soc >= 97:
                self._result("battery", intent, "skipped", why="full")
                continue
            min_soc = float(ctx.get("min_soc") or 10)
            if intent == "export" and soc is not None and soc <= min_soc + 5:
                self._result("battery", intent, "skipped", why="empty")
                continue
            c = dict(ctx)
            if intent == "export":
                c["target"] = c["_export_target"]
            elif intent == "hold" and soc is not None:
                c["target"] = round(soc)
            calls = self.ctl.calls("battery", {"intent": intent, "ctx": c})
            await self._step("battery", intent, calls, lambda fl, b, i=intent: _expect(i, fl, b), wait_s, base)

    async def _car(self) -> None:
        base: dict[str, Any] = {}
        top = 16
        for step, intent, amps in (("start", "charge", top), ("low", "charge", 6), ("stop", "stop", top)):
            if self._stop:
                return
            calls = self.ctl.calls("car", {"intent": intent, "ctx": {"current": amps}})
            await self._step("car", step, calls, lambda fl, b, s=step: _expect_car(s, fl, b), WAIT_S["car"], base)
            if step == "start":
                base["ev_high"] = self.ov.flow().get("ev")
                if not base["ev_high"] or base["ev_high"] < 1000:
                    self._result("car", "low", "skipped", why="not_charging")
                    self._result("car", "stop", "skipped", why="not_charging")
                    return

    # ---------- the report ----------
    def report_url(self) -> str | None:
        s = self.state
        res = s.get("results") or []
        if not res:
            return None
        import os
        prof = self.ctl.profile_key("battery")
        lines = [f"**Energy Pilot** {os.environ.get('BUILD_VERSION', 'dev')} · profile `{prof}` · model `{getattr(self.ctl, 'model', None)}`",
                 f"Battery integration `{self.ctl.platforms.get('battery')}` · charger `{self.ctl.platforms.get('car')}`", "",
                 "| Part | Step | Result | Details |", "|---|---|---|---|"]
        mark = {"ok": "✅", "fixed": "🔧", "failed": "❌", "skipped": "⏭️"}
        for r in res:
            det = ""
            if r["result"] == "fixed":
                det = f"`{r.get('entity')}`: `{r.get('option_from')}` → `{r.get('option_to')}`"
            elif r["result"] == "failed":
                bad = ", ".join("`%s`=%s" % (x["entity"], x["value"]) for x in r.get("rejected") or [])
                det = f"{r.get('why')} {bad} seen {r.get('seen')}"
            elif r["result"] == "skipped":
                det = str(r.get("why"))
            lines.append(f"| {r['part']} | {r['step']} | {mark.get(r['result'], r['result'])} | {det} |")
        left = (s.get("restored") or {}).get("left") or []
        if left:
            lines += ["", "Not put back: " + ", ".join("`%s`=%s" % (x["entity"], x["value"]) for x in left)]
        body = "\n".join(lines)[:6000]
        title = f"Test result: {prof or 'battery'}"
        return f"{REPO}?title={quote(title)}&labels=test-result&body={quote(body)}"


def _ctx_defaults() -> dict[str, Any]:
    from datetime import datetime

    from . import adapters

    return {"grid_charge": True, "min_soc": 10, "soc": 50, "target": 50, "rate": 10, "power_w": TEST_W, "max_power_w": TEST_W,
            "max_charge_w": TEST_W, "power_kw": TEST_W / 1000, "max_charge_kw": TEST_W / 1000, "max_power_kw": TEST_W / 1000,
            "export_w": 800, "house_w": 0, "device_id": "", "serial": "", "charge_a": 20,
            **adapters.alpha_windows(datetime.now())}


def _limit(ctx: dict[str, Any], soc: float | None) -> dict[str, Any]:
    """At most 1 kW, and a target a few percent away - so a step can't run on."""
    out = dict(ctx)
    for k in ("power_w", "export_w"):
        out[k] = min(float(out.get(k) or TEST_W), TEST_W if k == "power_w" else 800)
    out["power_kw"] = round(out["power_w"] / 1000, 2)
    if "charge_a" in out:
        out["charge_a"] = max(1, min(int(out["charge_a"] or 20), 20))
    if soc is not None:
        out["soc"] = round(soc)
        out["target"] = round(min(100, soc + 5))
    out["_export_target"] = round(max(float(out.get("min_soc") or 10), (soc or 50) - 5))
    return out

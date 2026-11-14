"""The panel (served through Home Assistant's ingress, or on its own port in Docker) and its small API."""

from __future__ import annotations

import os

from datetime import datetime
from pathlib import Path

from aiohttp import web

from . import adapters
from .overview import Overview
from .runner import CONTROL, OFF, SHADOW, Runner

FRONTEND = Path(__file__).parent / "frontend"


# Where "Send to the developer" goes (report-worker/worker.js on Cloudflare). Empty: the button falls back to a
# GitHub issue and the diagnostics download.
REPORT_URL = os.environ.get("EP_REPORT_URL", "https://ep-reports.clahen86.workers.dev")


def _fixed_lines(overview: Overview) -> list:
    """What was mended by itself, and the shared fixes from other installations in use here."""
    a = getattr(overview, "autofix", None)
    lines = a.lines() if a else []
    c = overview.controller
    for k, f in ((c.__dict__.get("community_used") or {}) if c else {}).items():
        lines.append({"key": f"community|{k}", "what": "community", "from": f["from"], "to": f["to"], "intent": f["intent"], "t": 0})
    return lines


def _tested(overview: Overview) -> dict | None:
    """The last self-test in short, for the status light: none / ok / fixed / failed, and whether it runs."""
    t = getattr(overview, "selftest", None)
    if not t:
        return None
    st = t.state
    res = st.get("results") or []
    running = bool(t._task and not t._task.done())
    if not res and not running:
        return {"result": "none", "skipped": bool(overview.settings.get("test_skipped"))}
    worst = "failed" if any(r["result"] == "failed" for r in res) else "fixed" if any(r["result"] == "fixed" for r in res) else "ok"
    return {"result": worst, "running": running, "report_url": t.report_url() if res and worst == "failed" else None}


def make_app(runner: Runner, overview: Overview) -> web.Application:
    app = web.Application(client_max_size=10 * 1024 * 1024)  # "Get help" may carry a few pictures

    def lang(req: web.Request) -> str:
        code = str(req.query.get("lang", overview.settings.get("language") or "da"))[:2].lower()
        code = "nb" if code in ("no", "nn") else code
        return code if code in ("da", "en", "de", "fr", "nl", "sv", "nb") else "en"

    async def get_overview(req: web.Request) -> web.Response:
        data = overview.snapshot(lang(req))
        st = runner.status()
        data["shadow"] = [{k: a[k] for k in ("name", "mode", "agree", "checks", "errors")} for a in st["apps"]]
        data["connected"] = st["connected"]
        c = overview.controller
        data["in_control"] = [p for p in c.parts() if c.mode(p) == "control"] if c else []  # Energy Pilot's own parts
        data["setup_done"] = bool(overview.settings.get("setup_done"))
        data["currency"] = runner.ha.config.get("currency") or "EUR"
        data["price_info"] = overview.price_info
        if overview.engine:
            from datetime import datetime as _dt
            from zoneinfo import ZoneInfo as _Z

            other = None
            if (e := overview.role("battery_cost")) and (stc := runner.ha.states.get(e)):
                try:
                    other = float(stc.get("state"))
                except (TypeError, ValueError):
                    other = None
                # Another system's number only when it's believable: at most three times the dearest price
                # (a glitch once made it 5,208 kr/kWh) - otherwise Energy Pilot's own is shown.
                top = max((h["price"] for h in (data.get("plan") or {}).get("hours", []) if "price" in h), default=5.0)
                if other is not None and not 0 <= other <= 3 * max(top, 1.0):
                    other = None
                # Not when Energy Pilot runs the battery itself (the other system is paused then and its number
                # stands still), nor a 0 while the battery holds power.
                c = overview.controller
                if c and c.mode("battery") == "control":
                    other = None
                if other == 0 and overview.engine.ledger.state.get("stored_kwh", 0) > 0.5:
                    other = None
            data["ledger"] = overview.engine.ledger.summary(_dt.now(_Z(runner.ha.config.get("time_zone") or "UTC")), other)
            soc = (overview.flow() or {}).get("soc")
            if soc is not None:
                data["ledger"]["battery_kwh"] = round(soc / 100 * overview.engine.settings().capacity_kwh, 1)
        eng = overview.engine
        if eng and eng.result:
            b = eng.result.get("battery") or {}
            a = eng.agree
            data["engine"] = {"saving": b.get("saving"), "now": b.get("now"), "capacity": b.get("capacity"),
                              "agree": round(100 * a["same"] / a["checks"]) if a["checks"] else None, "checks": a["checks"],
                              "profile": bool(eng.profile), "car": eng.result.get("car"), "cars": eng.result.get("cars"), "things": eng.things.view(overview.settings, datetime.now(eng.tz)), "generator": eng.result.get("generator"), "sources": eng.sources_used(), "learning": eng.learning.summary(), "blend": eng.blend_info(),
                              "decision": overview.engine_decision(lang(req)), "selfcheck": eng.follow.check() + eng.checks + (overview.controller.watch_checks() if overview.controller else []),
                              "fixed": _fixed_lines(overview),
                              "tested": _tested(overview)}
        return web.json_response(data)

    async def get_settings(_req: web.Request) -> web.Response:
        guess = overview.engine._guess_capacity() if overview.engine else None
        from .sources import ZONES, price_area

        country = (runner.ha.config.get("country") or "DK").upper()
        area = price_area(float(runner.ha.config.get("latitude") or 56), float(runner.ha.config.get("longitude") or 10), country)
        return web.json_response({"settings": overview.settings, "roles": overview.roles(), "capacity_guess": guess, "area_guess": area,
                                  "zones": ZONES.get(country, []), "tou_presets": __import__("energy_pilot.sources", fromlist=["TOU_PRESETS"]).TOU_PRESETS, "country": country, "currency": runner.ha.config.get("currency"),
                                  "sources": {r: overview.source(r) for r in overview.roles()},
                                  "candidates": overview.candidates(),
                                  "ev_detected": overview.engine.ev_detected if overview.engine else None,
                                  "all_sensors": overview.all_sensors(),
                                  "battery_sign_found": overview.engine.sign_found() if overview.engine else None,
                                  "grid_sign_found": overview.grid_sign_found(),
                                  "power_tariff": overview.engine.power_tariff() if overview.engine else None,
                                  "month_peak": overview.engine.month_peak.level() if overview.engine else None,
                                  "capacity_learned": overview.engine.batt_learn.capacity() if overview.engine else None,
                                  "wear_default": overview.engine.wear(own=False) if overview.engine else None,
                                  "battery_type_found": overview.engine.battery_type() if overview.engine else None,
                                  "roles_all": {r: overview.role_all(r) for r in ("pv_power", "solar_today", "solar_tomorrow")},
                                  "charger_switches": switches(), "thing_options": thing_options()})

    def thing_options() -> dict:
        """For Settings → Runs cheaply: the switches, start buttons and power sensors that make sense (and all, on request)."""
        from . import things as _things

        c = overview.controller
        used = {e for e in (overview.role(r) for r in ("pv_power", "grid_power", "house_power", "battery_power", "ev_power")) if e}
        return _things.options(getattr(c, "registry", []) or [], getattr(c, "_devices", {}) or {}, runner.ha.states, used)

    def switches() -> dict | None:
        """For Settings → Car → Control: the switches that can start a charger, and what each charger uses now."""
        c = overview.controller
        if not c:
            return None
        parts = ["car", *c.car_parts()]
        return {"options": c.switch_options, "used": {p: c.auto_switch(p) for p in parts},
                "onoff": {p: c.onoff(p) for p in parts},
                "native": {p: c.platforms.get(p) in adapters.CHARGER_SERVICES for p in parts}}

    async def redetect(_req: web.Request) -> web.Response:
        await overview.async_detect()
        return web.json_response({"ok": True})

    async def save_settings(req: web.Request) -> web.Response:
        body = await req.json()
        ua = req.headers.get("User-Agent") or ""
        overview.save(body, "home_assistant" if "HomeAssistant" in ua or "aiohttp" in ua.lower() else "app")
        if overview.controller and ("ev_switch" in body or "chargers" in body or "things" in body or "things_dismissed" in body):
            try:
                await overview.controller.discover()  # the chosen switch is used at once
            except Exception:  # noqa: BLE001
                pass
        if overview.engine:
            try:
                overview.engine.run()  # the new choices show at once
            except Exception:  # noqa: BLE001
                pass
        return web.json_response({"ok": True})

    async def things_arm(req: web.Request) -> web.Response:
        """A machine is ready (loaded, door shut): Energy Pilot may start it at the best time - or not after all."""
        body = await req.json()
        if not overview.engine or not body.get("id"):
            return web.json_response({"error": "bad request"}, status=400)
        overview.engine.things.arm(str(body["id"]), bool(body.get("armed")))
        try:
            overview.engine.run()
        except Exception:  # noqa: BLE001
            pass
        return web.json_response({"ok": True})

    async def ev(req: web.Request) -> web.Response:
        """The car buttons: they change the same helpers your dashboard does - a person's choice, so also in shadow."""
        body = await req.json()
        ents = (overview.ev() or {}).get("entities") or {}
        if "manual" in body:
            if ents.get("ev_manual"):
                await runner.ha.call_service("input_boolean", "turn_on" if body["manual"] else "turn_off", {"entity_id": ents["ev_manual"]})
            else:
                overview.save({"ev_now": bool(body["manual"])})
        if "ready" in body:
            if ents.get("ev_ready"):
                await runner.ha.call_service("input_datetime", "set_datetime", {"entity_id": ents["ev_ready"], "time": body["ready"]})
            else:
                overview.save({"ev_ready": body["ready"]})
        if "cap" in body:
            if ents.get("ev_cap"):
                await runner.ha.call_service("input_number", "set_value", {"entity_id": ents["ev_cap"], "value": float(body["cap"])})
            else:
                overview.save({"ev_need_kwh": float(body["cap"])})
        if "target" in body:
            overview.save({"ev_target": max(20, min(100, int(body["target"])))})
        if "trip" in body:
            overview.save({"ev_trip": bool(body["trip"])})
        if "sun_target" in body:  # 0/None: the same as the grid target
            v = body["sun_target"]
            overview.save({"ev_sun_target": max(20, min(100, int(v))) if v else None})
        return web.json_response({"ok": True})

    async def index(_req: web.Request) -> web.FileResponse:
        return web.FileResponse(FRONTEND / "index.html", headers={"Cache-Control": "no-cache"})

    async def status(_req: web.Request) -> web.Response:
        return web.json_response(runner.status())

    async def mode(req: web.Request) -> web.Response:
        body = await req.json()
        if body.get("mode") not in (SHADOW, CONTROL, OFF) or body.get("app") not in runner.apps:
            return web.json_response({"error": "bad request"}, status=400)
        runner.set_mode(body["app"], body["mode"])
        return web.json_response({"ok": True})

    async def stop_all(_req: web.Request) -> web.Response:
        runner.all_to_shadow()
        if overview.controller:
            await overview.controller.release()
        return web.json_response({"ok": True})

    def build_diagnostics() -> dict:
        """What it sees, what it planned and why - no tokens or passwords."""
        import os
        from datetime import datetime as _dt

        eng = overview.engine
        roles = overview.roles()
        ents = sorted({e for v in roles.values() for e in (v if isinstance(v, list) else [v]) if e})
        secret = ("token", "password", "api_key", "apikey", "secret")
        settings = {k: v for k, v in overview.settings.items() if not any(w in k.lower() for w in secret)}
        out = {
            "made": _dt.now().isoformat(timespec="seconds"),
            "version": os.environ.get("BUILD_VERSION", "dev"),
            "ha": {k: runner.ha.config.get(k) for k in ("version", "country", "currency", "time_zone", "unit_system")},
            "settings": settings,
            "roles": roles,
            "states": {e: {"state": (runner.ha.states.get(e) or {}).get("state"),
                           "attributes": {k: v for k, v in ((runner.ha.states.get(e) or {}).get("attributes") or {}).items()
                                          if not any(w in k.lower() for w in secret)}} for e in ents},
            "flow": overview.flow(),
            "plan": overview.plan(),
            "price_info": overview.price_info,
            "engine": None,
            "control": overview.controller.status() if overview.controller else None,
        }
        if eng:
            b = eng.settings()
            out["engine"] = {"battery": {k: (sorted(v) if isinstance(v, frozenset) else v) for k, v in b.__dict__.items()},
                             "result": eng.result, "checks": eng.checks, "learning": eng.learning.summary(),
                             "blend": eng.blend_info(), "sources": eng.sources_used(), "grid_peak_kw": eng.grid_peak.kw(),
                             "sell_prices": {k.isoformat(): v for k, v in sorted(eng.sell_prices().items())}}
        return out

    async def diagnostics(req: web.Request) -> web.Response:
        """One file to send when something looks wrong."""
        from datetime import datetime as _dt

        out = build_diagnostics()
        name = f"energy_pilot_diagnostics_{_dt.now():%Y%m%d_%H%M}.json"
        return web.json_response(out, dumps=lambda o: __import__("json").dumps(o, default=str, indent=1),
                                 headers={"Content-Disposition": f'attachment; filename="{name}"'})

    app.router.add_get("/api/diagnostics", diagnostics)
    app.router.add_get("/", index)
    app.router.add_get("/api/status", status)
    app.router.add_get("/api/overview", get_overview)
    app.router.add_get("/api/settings", get_settings)
    app.router.add_post("/api/settings", save_settings)
    app.router.add_post("/api/detect", redetect)

    async def control_status(_req: web.Request) -> web.Response:
        c = overview.controller
        return web.json_response(c.status() if c else {})

    async def control_mode(req: web.Request) -> web.Response:
        body = await req.json()
        c = overview.controller
        if not c or body.get("part") not in c.parts() or body.get("mode") not in ("shadow", "control", "off"):
            return web.json_response({"error": "bad request"}, status=400)
        if body["mode"] != "control":
            await c.hand_back(body["part"])  # leaving control: the inverter back to normal and the owner's settings
        c.set_mode(body["part"], body["mode"])
        await c.tick()
        return web.json_response(c.status())

    async def control_release(_req: web.Request) -> web.Response:
        if overview.controller:
            await overview.controller.release()
        runner.all_to_shadow()
        return web.json_response({"ok": True})

    async def selftest_get(_req: web.Request) -> web.Response:
        t = getattr(overview, "selftest", None)
        return web.json_response(t.status() if t else {})

    async def selftest_post(req: web.Request) -> web.Response:
        t = getattr(overview, "selftest", None)
        if not t:
            return web.json_response({"error": "not ready"}, status=503)
        body = await req.json()
        act = body.get("action")
        if act == "start":
            t.start(list(body.get("parts") or ["battery"]))
        elif act == "stop":
            t.stop()
        elif act == "undo":
            t.undo(str(body.get("part")), str(body.get("intent")), str(body.get("entity")))
        elif act == "clear":
            if not t.status()["running"]:
                overview.save({"selftest": {}})
        return web.json_response(t.status())

    async def autofix_post(req: web.Request) -> web.Response:
        a = getattr(overview, "autofix", None)
        body = await req.json()
        key = str(body.get("undo") or "")
        if key.startswith("community|"):  # a shared fix undone: never used here again
            ign = list(overview.settings.get("community_ignore") or [])
            k = key.split("|", 1)[1]
            overview.save({"community_ignore": ign + [k]})
            if overview.controller:
                overview.controller.__dict__.get("community_used", {}).pop(k, None)
                overview.controller.last.pop("battery", None)
        elif a and key:
            a.undo(key)
        return web.json_response({"fixed": _fixed_lines(overview)})

    async def report(req: web.Request) -> web.Response:
        """'Send to the developer': the test result and the diagnostics go to the report receiver (report-worker/),
        which files them in a private repository - no GitHub account needed. Only when the user presses it."""
        import aiohttp

        url = REPORT_URL
        if not url:
            return web.json_response({"error": "not_configured"}, status=503)
        body = await req.json() if req.can_read_body else {}
        diag = build_diagnostics()
        ctl = diag.get("control") or {}
        for part in ctl.values():  # every control in Home Assistant: long, and names of rooms and people
            if isinstance(part, dict) and isinstance(part.get("profile"), dict):
                part["profile"].pop("all_controls", None)
        t = getattr(overview, "selftest", None)
        test = t.status() if t else {}
        test.pop("report_url", None)
        c = overview.controller
        # Up to 3 pictures (screenshots), already made smaller by the page - kept small here too.
        images = [{"name": str(i.get("name") or "billede")[:60], "data": i["data"]}
                  for i in (body.get("images") or [])[:3]
                  if isinstance(i, dict) and isinstance(i.get("data"), str) and len(i["data"]) <= 2_000_000]
        payload = {"note": str(body.get("note") or "")[:4000], "test": test, "diagnostics": diag, "images": images,
                   "profile": c.profile_key("battery") if c else None, "lang": str(body.get("lang") or "")[:5],
                   "install": overview.settings.get("install_id")}  # so the answer finds its way back here
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(url, json=payload, headers={"x-ep-client": "energy-pilot"},
                                  timeout=aiohttp.ClientTimeout(total=60)) as r:
                    res = await r.json(content_type=None)
                    if r.status != 200:
                        return web.json_response({"error": res.get("error") or f"http_{r.status}"}, status=502)
        except Exception as err:  # noqa: BLE001
            return web.json_response({"error": "unreachable", "detail": str(err)[:200]}, status=502)
        overview.save({"last_report": {"id": res.get("id"), "t": __import__("time").time()}, "replies": {}})
        return web.json_response({"ok": True, "id": res.get("id")})

    async def report_info(_req: web.Request) -> web.Response:
        return web.json_response({"available": bool(REPORT_URL), "last": overview.settings.get("last_report")})

    async def replies_get(req: web.Request) -> web.Response:
        """Answers to "Get help": the stored ones, fetched fresh when the page asks and they're older than 5 minutes."""
        tel = getattr(overview, "telemetry", None)
        if not tel:
            return web.json_response({})
        got = overview.settings.get("replies") or {}
        if tel.answer_every() and __import__("time").time() - float(got.get("t") or 0) > 300:
            await tel.fetch_answers()
        return web.json_response(tel.visible(mark_seen=True))

    async def replies_post(req: web.Request) -> web.Response:
        tel = getattr(overview, "telemetry", None)
        b = await req.json() if req.can_read_body else {}
        if tel and b.get("hide"):  # "Close" on an answer - it comes back with a new comment
            tel.hide(str(b["hide"]))
            return web.json_response({"ok": True, "replies": tel.visible()})
        if not tel or not str(b.get("text") or "").strip():
            return web.json_response({"ok": False, "error": "content"}, status=400)
        res = await tel.write_back(b.get("id"), b.get("text"))
        return web.json_response({**res, "replies": tel.visible()}, status=200 if res.get("ok") else 502)

    app.router.add_post("/api/report", report)
    app.router.add_get("/api/replies", replies_get)
    app.router.add_post("/api/replies", replies_post)
    app.router.add_get("/api/report", report_info)
    app.router.add_post("/api/autofix", autofix_post)
    app.router.add_get("/api/selftest", selftest_get)
    app.router.add_post("/api/selftest", selftest_post)
    app.router.add_get("/api/control", control_status)
    app.router.add_post("/api/control", control_mode)
    app.router.add_post("/api/control/release", control_release)
    app.router.add_post("/api/ev", ev)
    app.router.add_post("/api/things/arm", things_arm)
    app.router.add_post("/api/mode", mode)
    app.router.add_post("/api/shadow_all", stop_all)
    app.router.add_static("/static", FRONTEND)
    return app

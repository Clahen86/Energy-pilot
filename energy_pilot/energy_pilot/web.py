"""The panel (served through Home Assistant's ingress, or on its own port in Docker) and its small API."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from aiohttp import web

from . import adapters
from .overview import Overview
from .runner import CONTROL, OFF, SHADOW, Runner

FRONTEND = Path(__file__).parent / "frontend"


def make_app(runner: Runner, overview: Overview) -> web.Application:
    app = web.Application()

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
                              "decision": overview.engine_decision(lang(req)), "selfcheck": eng.follow.check() + eng.checks + (overview.controller.watch_checks() if overview.controller else [])}
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

    async def diagnostics(req: web.Request) -> web.Response:
        """One file to send when something looks wrong: what it sees, what it planned and why - no tokens or passwords."""
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

    app.router.add_get("/api/control", control_status)
    app.router.add_post("/api/control", control_mode)
    app.router.add_post("/api/control/release", control_release)
    app.router.add_post("/api/ev", ev)
    app.router.add_post("/api/things/arm", things_arm)
    app.router.add_post("/api/mode", mode)
    app.router.add_post("/api/shadow_all", stop_all)
    app.router.add_static("/static", FRONTEND)
    return app

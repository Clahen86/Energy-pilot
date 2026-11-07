"""The panel (served through Home Assistant's ingress, or on its own port in Docker) and its small API."""

from __future__ import annotations

from pathlib import Path

from aiohttp import web

from .overview import Overview
from .runner import CONTROL, OFF, SHADOW, Runner

FRONTEND = Path(__file__).parent / "frontend"


def make_app(runner: Runner, overview: Overview) -> web.Application:
    app = web.Application()

    def lang(req: web.Request) -> str:
        return "da" if req.query.get("lang", overview.settings.get("language") or "da").startswith("da") else "en"

    async def get_overview(req: web.Request) -> web.Response:
        data = overview.snapshot(lang(req))
        st = runner.status()
        data["shadow"] = [{k: a[k] for k in ("name", "mode", "agree", "checks", "errors")} for a in st["apps"]]
        data["connected"] = st["connected"]
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
                              "profile": bool(eng.profile), "car": eng.result.get("car"), "sources": eng.sources_used(), "learning": eng.learning.summary(), "blend": eng.blend_info(),
                              "decision": overview.engine_decision("da" if lang(req) == "da" else "en")}
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
                                  "roles_all": {r: overview.role_all(r) for r in ("pv_power", "solar_today", "solar_tomorrow")}})

    async def redetect(_req: web.Request) -> web.Response:
        await overview.async_detect()
        return web.json_response({"ok": True})

    async def save_settings(req: web.Request) -> web.Response:
        overview.save(await req.json())
        if overview.engine:
            try:
                overview.engine.run()  # the new choices show at once
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
        if not c or body.get("part") not in ("battery", "car") or body.get("mode") not in ("shadow", "control", "off"):
            return web.json_response({"error": "bad request"}, status=400)
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
    app.router.add_post("/api/mode", mode)
    app.router.add_post("/api/shadow_all", stop_all)
    app.router.add_static("/static", FRONTEND)
    return app

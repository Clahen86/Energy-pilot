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
        return web.json_response(data)

    async def get_settings(_req: web.Request) -> web.Response:
        return web.json_response({"settings": overview.settings, "roles": overview.roles(),
                                  "candidates": overview.candidates()})

    async def save_settings(req: web.Request) -> web.Response:
        overview.save(await req.json())
        return web.json_response({"ok": True})

    async def ev(req: web.Request) -> web.Response:
        """The car buttons: they change the same helpers your dashboard does - a person's choice, so also in shadow."""
        body = await req.json()
        ents = (overview.ev() or {}).get("entities") or {}
        if "manual" in body and ents.get("ev_manual"):
            await runner.ha.call_service("input_boolean", "turn_on" if body["manual"] else "turn_off",
                                         {"entity_id": ents["ev_manual"]})
        if "ready" in body and ents.get("ev_ready"):
            await runner.ha.call_service("input_datetime", "set_datetime", {"entity_id": ents["ev_ready"], "time": body["ready"]})
        if "cap" in body and ents.get("ev_cap"):
            await runner.ha.call_service("input_number", "set_value", {"entity_id": ents["ev_cap"], "value": float(body["cap"])})
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
        return web.json_response({"ok": True})

    app.router.add_get("/", index)
    app.router.add_get("/api/status", status)
    app.router.add_get("/api/overview", get_overview)
    app.router.add_get("/api/settings", get_settings)
    app.router.add_post("/api/settings", save_settings)
    app.router.add_post("/api/ev", ev)
    app.router.add_post("/api/mode", mode)
    app.router.add_post("/api/shadow_all", stop_all)
    app.router.add_static("/static", FRONTEND)
    return app

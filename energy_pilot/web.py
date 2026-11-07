"""The panel (served through Home Assistant's ingress, or on its own port in Docker) and its small API."""

from __future__ import annotations

from pathlib import Path

from aiohttp import web

from .runner import CONTROL, OFF, SHADOW, Runner

FRONTEND = Path(__file__).parent / "frontend"


def make_app(runner: Runner) -> web.Application:
    app = web.Application()

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
    app.router.add_post("/api/mode", mode)
    app.router.add_post("/api/shadow_all", stop_all)
    app.router.add_static("/static", FRONTEND)
    return app

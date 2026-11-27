"""The panel (served through Home Assistant's ingress, or on its own port in Docker) and its small API."""

from __future__ import annotations

import asyncio
import base64
import hmac
import logging
import os
import secrets

from datetime import datetime
from zoneinfo import ZoneInfo
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


ASK_AGAIN_S = 14 * 86400  # a skipped self-test is offered again after two weeks


def test_skipped(v: object, now: float | None = None) -> bool:
    """Skipped the self-test: for good when it was skipped before this came (True), else for two weeks."""
    import time

    if isinstance(v, bool) or v is None:
        return bool(v)
    try:
        return (now or time.time()) - float(v) < ASK_AGAIN_S
    except (TypeError, ValueError):
        return False


def _tested(overview: Overview) -> dict | None:
    """The last self-test in short, for the status light: none / ok / fixed / failed, and whether it runs."""
    t = getattr(overview, "selftest", None)
    if not t:
        return None
    st = t.state
    res = st.get("results") or []
    running = bool(t._task and not t._task.done())
    if not res and not running:
        return {"result": "none", "skipped": test_skipped(overview.settings.get("test_skipped"))}
    worst = "failed" if any(r["result"] == "failed" for r in res) else "fixed" if any(r["result"] == "fixed" for r in res) else "ok"
    return {"result": worst, "running": running, "report_url": t.report_url() if res and worst == "failed" else None}


def panel_password(data_dir: Path) -> str | None:
    """In Docker the panel is on its own port with no login in front: it gets a password (EP_PASSWORD, or one made
    once and written to the log). The add-on is reached only through Home Assistant's own login (ingress)."""
    if os.environ.get("SUPERVISOR_TOKEN"):
        return None
    if pw := os.environ.get("EP_PASSWORD"):
        return pw
    f = data_dir / "panel_password"
    try:
        pw = f.read_text().strip()
    except OSError:
        pw = ""
    if not pw:
        pw = secrets.token_urlsafe(12)
        try:
            f.write_text(pw)
        except OSError:
            pass
    logging.getLogger(__name__).warning("Panel password (any user name; set EP_PASSWORD to choose your own): %s", pw)
    return pw


def _auth_ok(header: str | None, password: str) -> bool:
    if not header or not header.lower().startswith("basic "):
        return False
    try:
        given = base64.b64decode(header[6:]).decode().split(":", 1)[1]
    except (ValueError, IndexError, UnicodeDecodeError):
        return False
    return hmac.compare_digest(given.encode(), password.encode())


# The add-on: only Home Assistant itself (the companion integration, 172.30.32.1) and the Supervisor's ingress
# (172.30.32.2, the panel behind HA's login) - other containers on HA's internal network can't reach the panel.
ADDON_FROM = {"172.30.32.1", "172.30.32.2", "127.0.0.1", "::1"}


def guard(password: str | None, addon: bool | None = None) -> object:
    addon = bool(os.environ.get("SUPERVISOR_TOKEN")) if addon is None else addon

    @web.middleware
    async def middleware(req: web.Request, handler: object) -> web.StreamResponse:
        if addon and req.remote not in ADDON_FROM:
            return web.Response(status=403, text="Only through Home Assistant")
        if password and not _auth_ok(req.headers.get("Authorization"), password):
            return web.Response(status=401, headers={"WWW-Authenticate": 'Basic realm="Energy Pilot"'})
        # Changes only as JSON: a web page elsewhere can't send that without the browser asking first (CORS), and it
        # is never allowed - so a page someone in the house opens can't turn control on or change the settings.
        if req.method not in ("GET", "HEAD", "OPTIONS") and req.content_type != "application/json":
            return web.json_response({"error": "json_only"}, status=415)
        return await handler(req)
    return middleware


def make_app(runner: Runner, overview: Overview, password: str | None = None) -> web.Application:
    app = web.Application(client_max_size=10 * 1024 * 1024, middlewares=[guard(password)])  # "Get help" may carry a few pictures

    def lang(req: web.Request) -> str:
        code = str(req.query.get("lang", overview.settings.get("language") or overview.ha.config.get("language") or "en"))[:2].lower()
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
        from . import companion

        data["companion"] = companion.status()  # "app": the panel offers the move to HACS (one tap)
        data["companion_snooze"] = overview.settings.get("companion_snooze")
        # the front page asks once whether to share hour by hour (None: not answered yet)
        data["share_hours"] = overview.settings.get("share_hours") if overview.settings.get("share_anonymous", True) is not False else False
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
            data["ledger"]["view"] = overview.settings.get("saved_view") or "bat"
            data["whatif"] = getattr(overview.engine, "whatif", None)
            tf = getattr(overview, "tariffs", None)
            data["tariffs"] = None
            if tf and overview.settings.get("tariff_show", True):
                data["tariffs"] = tf.result
                if not tf.result and (choices := tf.choices()):
                    # Not 7 days of hours yet: the card says so, and the user can already pick their deal.
                    hourly = getattr(overview, "hourly", None)
                    have = len(hourly.days(_dt.now(_Z(runner.ha.config.get("time_zone") or "UTC")).date().isoformat())) if hourly else 0
                    cur = next((c for c in choices if c["id"] == overview.settings.get("tariff_current")), None)
                    data["tariffs"] = {"mode": "collecting", "days": have, "need": 7, "current": cur}
            soc = (overview.flow() or {}).get("soc")
            if soc is not None:
                data["ledger"]["battery_kwh"] = round(soc / 100 * overview.engine.settings().capacity_kwh, 1)
        eng = overview.engine
        if eng and eng.result:
            b = eng.result.get("battery") or {}
            a = eng.agree
            data["engine"] = {"saving": b.get("saving"), "now": b.get("now"), "capacity": b.get("capacity"),
                              "agree": round(100 * a["same"] / a["checks"]) if a["checks"] else None, "checks": a["checks"],
                              "profile": bool(eng.profile), "car": eng.result.get("car"), "cars": eng.result.get("cars"), "things": eng.things.view(overview.settings, datetime.now(eng.tz)), "generator": eng.result.get("generator"), "sources": eng.sources_used(), "learning": eng.learning.summary(), "blend": eng.blend_info(), "retro": eng.retro_shown(),
                              "decision": overview.engine_decision(lang(req)), "selfcheck": eng.follow.check() + eng.checks + (overview.controller.watch_checks() if overview.controller else []),
                              "fixed": _fixed_lines(overview),
                              "can_sell": bool(eng.can_export()),
                              "tested": _tested(overview)}
        try:
            from . import trial

            data["trial"] = trial.view(overview, (_tested(overview) or {}).get("result"), datetime.now(ZoneInfo(runner.ha.config.get("time_zone") or "UTC")))
        except Exception:  # noqa: BLE001 - only a hint
            data["trial"] = None
            # For the companion's entities: the battery's health (what it really holds against its label, learned) and
            # whether something needs a look (a warning in the self-check, or Home Assistant not answering)
            try:
                lc, nominal = eng.batt_learn.capacity(), overview.settings.get("battery_kwh")
                data["battery_health"] = {"pct": round(100 * float(lc) / float(nominal)), "learned_kwh": round(float(lc), 1),
                                          "nominal_kwh": round(float(nominal), 1)} if lc and nominal else None
            except (TypeError, ValueError, ZeroDivisionError):
                data["battery_health"] = None
            warn = [c.get("key") for c in data["engine"]["selfcheck"] if c.get("level") in ("warn", "error")]
            data["problem"] = {"on": bool(warn) or not data.get("connected", True), "keys": warn}
        return web.json_response(data)

    def _phase_ctl() -> dict[str, str | None]:
        """Which chargers have their own 1/3-phase choice (so the setting can be shown)."""
        ctl = overview.controller
        if not ctl:
            return {}
        from .adapters import phase_control

        out = {}
        for part in ["car", *getattr(ctl, "car_parts", lambda: [])()]:
            pc = phase_control((getattr(ctl, "entities", None) or {}).get(part) or [], runner.ha.states)
            out[part] = pc["entity"] if pc else None
        return out

    async def get_settings(_req: web.Request) -> web.Response:
        guess = overview.engine._guess_capacity() if overview.engine else None
        from .sources import ZONES, price_area

        country = (runner.ha.config.get("country") or "DK").upper()
        area = price_area(float(runner.ha.config.get("latitude") or 56), float(runner.ha.config.get("longitude") or 10), country)
        return web.json_response({"settings": overview.settings, "roles": overview.roles(), "capacity_guess": guess, "area_guess": area,
                                  "zones": ZONES.get(country, []), "tou_presets": __import__("energy_pilot.sources", fromlist=["TOU_PRESETS"]).TOU_PRESETS, "country": country, "currency": runner.ha.config.get("currency"), "bare_spot": overview.bare_spot(), "phase_meters": overview.phase_meters(), "night_update_ok": __import__("energy_pilot.nightupdate", fromlist=["possible"]).possible(),
                                  "sources": {r: overview.source(r) for r in overview.roles()},
                                  "candidates": overview.candidates(),
                                  "phase_ctl": _phase_ctl(),
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
                                  "charger_switches": switches(), "thing_options": thing_options(), "charger_devices": charger_devices(),
                                  "car_plugs": car_plugs(),
                                  "curtail": overview.curtail.status() if getattr(overview, "curtail", None) else None})

    def car_plugs() -> list:
        """For Settings > Car > Cars: the car's own "plugged in" (or charging state) sensors - only from a car's own
        integration (Tesla, VW, Kia …), never the charger's: the charger already tells that a car is in it."""
        import re as _re

        from .chargers import extras
        from .detect import CAR_PLATFORMS

        reg = getattr(overview.controller, "_ent_reg", None) or {}
        # The car's own integration is also the one its battery level comes from - any brand, known here or not
        # (Lynk & Co wasn't on the list, and its "charger connection status" couldn't be picked).
        socs = {overview.role("ev_soc")} | {c.get("soc") for c in overview.settings.get("cars") or [] if isinstance(c, dict)}
        car_platforms = (set(CAR_PLATFORMS) | {(reg.get(e) or {}).get("platform") for e in socs if e}) - {"ocpp", "evcc_intg", None}
        words = _re.compile(r"plug|cable|kabel|connect|charging_state|charge_state|charger_state|charging_status|ladekabel|stik")
        chargers_own = {overview.role("ev_plug")} | {c.get("plug") for c in extras(overview.settings)}
        out = []
        for e, s in runner.ha.states.items():
            if not (e.startswith("binary_sensor.") or e.startswith("sensor.")) or e in chargers_own or not words.search(e):
                continue
            if (reg.get(e) or {}).get("platform") not in car_platforms:
                continue
            out.append({"entity_id": e, "name": str((s.get("attributes") or {}).get("friendly_name") or e)})
        return sorted(out, key=lambda x: (not x["entity_id"].startswith("binary_sensor."), x["name"].lower()))

    def charger_devices() -> list:
        """For Settings > Car: the chargers found, each with its power, plug, charged-energy and car-level sensors."""
        from .detect import charger_devices as _cd

        c = overview.controller
        try:
            return _cd(list((getattr(c, "_ent_reg", None) or {}).values()), getattr(c, "_devices", {}) or {}, runner.ha.states)
        except Exception:  # noqa: BLE001 - never in the way of the settings page
            return []

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
        if isinstance(body.get("_set_number"), dict):  # a check's fix on the inverter itself (its peak shaving)
            n = body.pop("_set_number")
            if str(n.get("entity_id") or "").startswith("number."):
                try:
                    await runner.ha.call_service("number", "set_value", {"entity_id": n["entity_id"], "value": float(n["value"])})
                except Exception:  # noqa: BLE001
                    pass
            if not body:
                if overview.engine:
                    try:
                        overview.engine.run()
                    except Exception:  # noqa: BLE001
                        pass
                return web.json_response({"ok": True})
        if isinstance(body.get("cars"), list):  # a new car gets its id here
            from .carlist import new_id

            body["cars"] = [{**c, "id": c.get("id") or new_id()} for c in body["cars"] if isinstance(c, dict)]
        ua = req.headers.get("User-Agent") or ""
        overview.save(body, "home_assistant" if "HomeAssistant" in ua or "aiohttp" in ua.lower() else "app")
        if overview.controller and ("ev_switch" in body or "chargers" in body or "things" in body or "things_dismissed" in body
                                    or "roles" in body):
            try:
                await overview.controller.discover()  # the chosen switch - or a charger picked by its sensors - is used at once
            except Exception:  # noqa: BLE001
                pass
        if overview.engine and set(body) & {"tariff", "markup", "vat", "price_area", "price_source"}:
            overview.engine._prices_at = 0.0  # the own spot prices are fetched again with the new taxes and area
        if overview.engine and set(body) - {"saved_view"}:  # only what the card shows: no new plan
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
        from . import carlist

        car = carlist.car_in(overview.settings, "car")
        if car is not None:  # more cars than chargers: ready, at most, target and trip belong to the car in it
            mine = {}
            if "ready" in body:
                mine["ready"] = str(body.pop("ready"))[:5] or None
            if "cap" in body:
                mine["need_kwh"] = max(0.0, min(200.0, float(body.pop("cap"))))
            if "target" in body:
                mine.update(target=max(20, min(100, int(body.pop("target")))), trip=False)
            if "trip" in body:
                mine["trip"] = bool(body.pop("trip"))
            if mine:
                overview.save(carlist.update_car(overview.settings, car["id"], mine))
                if overview.engine:
                    try:
                        overview.engine.run()
                    except Exception:  # noqa: BLE001
                        pass
        if "manual" in body:
            if ents.get("ev_manual"):
                await runner.ha.call_service("input_boolean", "turn_on" if body["manual"] else "turn_off", {"entity_id": ents["ev_manual"]})
            else:
                overview.save({"ev_now": bool(body["manual"])})
            # "Charge now" acts at once - not at the next round (up to 5 minutes later).
            if overview.controller:
                async def _now() -> None:
                    await asyncio.sleep(2 if ents.get("ev_manual") else 0)  # the helper's new state reaches us first
                    try:
                        await overview.controller.tick(("car",))
                    except Exception:  # noqa: BLE001 - the next round does it then
                        logging.getLogger("energy_pilot.control").warning("Charge now: could not tell the charger at once", exc_info=True)
                asyncio.create_task(_now())
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

    async def charger(req: web.Request) -> web.Response:
        """An extra car's buttons (charger 2, 3 …: "n" is its number): charge now, ready at, at most (kWh), its target
        (%), the next trip and cheapest/solar - from the app, the dashboard card and the companion."""
        from . import chargers as _chargers

        body = await req.json()
        conf = list(overview.settings.get("chargers") or [])
        extras = _chargers.extras(overview.settings)
        try:
            c = extras[int(body["n"]) - 2]
        except (KeyError, ValueError, TypeError, IndexError):
            return web.json_response({"error": "no such car"}, status=400)
        c = dict(c)
        from . import carlist

        car = carlist.car_in(overview.settings, f"car{int(body['n'])}")
        if car is not None:  # the car's own settings go with the car, not the charger
            mine = {}
            if "ready" in body:
                mine["ready"] = str(body.pop("ready"))[:5] if body.get("ready") else None
            if "cap" in body:
                mine["need_kwh"] = max(0.0, min(200.0, float(body.pop("cap"))))
            if "target" in body:
                mine.update(target=max(20, min(100, int(body.pop("target")))), trip=False)
            if "trip" in body:
                mine["trip"] = bool(body.pop("trip"))
            if mine:
                overview.save(carlist.update_car(overview.settings, car["id"], mine))
        if "manual" in body:
            c["now"] = bool(body["manual"])
        if "ready" in body:
            c["ready"] = str(body["ready"])[:5] if body["ready"] else None
        if "cap" in body:
            c["need_kwh"] = max(0.0, min(200.0, float(body["cap"])))
        if "target" in body:
            c["target"] = max(20, min(100, int(body["target"])))
            c["trip"] = False
        if "trip" in body:
            c["trip"] = bool(body["trip"])
        if body.get("mode") in ("cheapest", "solar"):
            c["mode"] = body["mode"]
        conf[conf.index(extras[int(body["n"]) - 2])] = c
        overview.save({"chargers": conf})
        if overview.engine:
            try:
                overview.engine.run()
            except Exception:  # noqa: BLE001 - the next round plans it then
                pass
        if "manual" in body and overview.controller:  # "charge now" acts at once, not at the next round
            try:
                await overview.controller.tick((f"car{int(body['n'])}",))
            except Exception:  # noqa: BLE001
                logging.getLogger("energy_pilot.control").warning("Charge now: could not tell charger %s at once", body["n"], exc_info=True)
        return web.json_response({"ok": True})

    async def car_in(req: web.Request) -> web.Response:
        """Which car is in a charger, picked by hand ("part": car, car2 …; "car": the car's id or its name). It
        stays for this charge; unplugged, the next car is found by itself again."""
        from . import carlist

        body = await req.json()
        part, want = str(body.get("part") or "car"), str(body.get("car") or "")
        lst = carlist.cars(overview.settings)
        car = next((c for c in lst if c["id"] == want), None) or next((c for c in lst if (c.get("name") or "") == want), None)
        from .chargers import extras

        parts = ["car"] + [f"car{i + 2}" for i in range(len(extras(overview.settings)))]
        if car is None or part not in parts:
            return web.json_response({"error": "no such car or charger"}, status=400)
        overview.save(carlist.pick(overview.settings, part, car["id"]))
        if overview.engine:
            try:
                overview.engine.run()
            except Exception:  # noqa: BLE001
                pass
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
        if overview.settings.get("trial"):
            overview.save({"trial": None})
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
            "curtail": overview.curtail.status() if getattr(overview, "curtail", None) else None,
            # the inverter's own lowest battery levels (Deye's Low/Shutdown/Restart SOC ...): below them it won't discharge
            "inverter_floors": _floors(),
        }
        if eng:
            b = eng.settings()
            out["engine"] = {"battery": {k: (sorted(v) if isinstance(v, frozenset) else v) for k, v in b.__dict__.items()},
                             "result": eng.result, "checks": eng.checks, "learning": eng.learning.summary(),
                             "blend": eng.blend_info(), "sources": eng.sources_used(), "grid_peak_kw": eng.grid_peak.kw(),
                             "sell_prices": {k.isoformat(): v for k, v in sorted(eng.sell_prices().items())}}
        return out

    def _floors() -> dict[str, float]:
        from .checks import inverter_floors

        ctl = overview.controller
        ents = (getattr(ctl, "entities", None) or {}).get("battery") or [] if ctl else []
        try:
            return dict(inverter_floors(runner.ha.states, ents, restart=True))
        except Exception:  # noqa: BLE001 - diagnostics never fail for this
            return {}

    async def diagnostics(req: web.Request) -> web.Response:
        """One file to send when something looks wrong."""
        from datetime import datetime as _dt

        out = build_diagnostics()
        name = f"energy_pilot_diagnostics_{_dt.now():%Y%m%d_%H%M}.json"
        return web.json_response(out, dumps=lambda o: __import__("json").dumps(o, default=str, indent=1),
                                 headers={"Content-Disposition": f'attachment; filename="{name}"'})

    async def suggest(req: web.Request) -> web.Response:
        """"Fits your home too" (suggest.js): what HA has, for the shared suggestions - and what was shown or closed."""
        if req.method == "POST":
            b = await req.json() if req.can_read_body else {}
            overview.settings["suggest"] = b.get("value") if isinstance(b.get("value"), dict) else None
            overview.save({})
            return web.json_response({"ok": True})
        ha = runner.ha
        try:
            reg = (await ha.command({"type": "config/entity_registry/list_for_display"})).get("entities", [])
        except Exception:  # noqa: BLE001 - suggestions just get fewer
            reg = []
        keep = {"mobile_app", "zha", "mqtt", "zwave_js", "deconz"}
        cfg = ha.config or {}
        return web.json_response({
            "language": cfg.get("language") or "en",
            "config": {"components": cfg.get("components") or [], "country": cfg.get("country")},
            "states": {e: {"attributes": {k: v for k, v in (st.get("attributes") or {}).items() if k in ("device_class", "friendly_name")}}
                       for e, st in ha.states.items()},
            "entities": {r["ei"]: {"entity_id": r["ei"], "platform": r.get("pl"), "device_id": r.get("di")} for r in reg if r.get("pl") in keep},
            "store": overview.settings.get("suggest"),
        })

    app.router.add_get("/api/suggest", suggest)
    app.router.add_post("/api/suggest", suggest)
    app.router.add_get("/api/diagnostics", diagnostics)
    app.router.add_get("/", index)
    app.router.add_get("/api/status", status)
    app.router.add_get("/api/overview", get_overview)
    async def tariff_choices(req: web.Request) -> web.Response:
        """The deals the user may pick as their own (Denmark, UK)."""
        tf = getattr(overview, "tariffs", None)
        return web.json_response({"choices": tf.choices() if tf else [], "current": overview.settings.get("tariff_current")})

    app.router.add_get("/api/tariffs", tariff_choices)
    app.router.add_get("/api/settings", get_settings)
    app.router.add_post("/api/settings", save_settings)
    app.router.add_post("/api/detect", redetect)

    async def entity_info(req: web.Request) -> web.Response:
        """A control's choices for the guide to an own profile: a select's options, a number's range, its value now."""
        out = {}
        for e in str(req.query.get("e", "")).split(",")[:40]:
            s = overview.ha.states.get(e) or {}
            a = s.get("attributes") or {}
            out[e] = {"state": s.get("state"), "options": a.get("options") if isinstance(a.get("options"), list) else None,
                      "min": a.get("min"), "max": a.get("max"), "unit": a.get("unit_of_measurement"),
                      "name": a.get("friendly_name")}
        return web.json_response(out)

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
        if overview.settings.get("trial"):
            overview.save({"trial": None})  # chosen by hand: the trial's own end no longer applies
        await c.tick()
        return web.json_response(c.status())

    async def trial_post(req: web.Request) -> web.Response:
        """"Try control for 24 hours" / "Not now" / "Keep controlling" / "Stop" / "OK" (trial.py)."""
        from . import trial

        body = await req.json() if req.can_read_body else {}
        act, now = body.get("action"), datetime.now(ZoneInfo(runner.ha.config.get("time_zone") or "UTC"))
        c = overview.controller
        if act == "start":
            ok = trial.start(overview, now)
            if ok and c:
                await c.tick()
            return web.json_response({"ok": ok})
        if act == "stop":
            await trial.end(overview, now)
        elif act == "keep" and c:  # after the trial: control for good
            for p in (overview.settings.get("trial_done") or {}).get("parts") or [p for p in ["battery", *c.bat_parts()] if not c.blocked(p)]:
                c.set_mode(p, "control")
            overview.save({"trial_done_seen": True})
            await c.tick()
        elif act == "no":
            overview.save({"ready_no": __import__("time").time()})
        elif act == "seen":
            overview.save({"trial_done_seen": True})
        return web.json_response({"ok": True})

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
        seen = str(body.get("seen") or "")
        if seen and a and not seen.startswith("community|"):  # OK: kept, the line goes away
            a.seen(seen)
        elif key.startswith("community|"):  # a shared fix undone: never used here again
            ign = list(overview.settings.get("community_ignore") or [])
            k = key.split("|", 1)[1]
            overview.save({"community_ignore": ign + [k]})
            if overview.controller:
                overview.controller.__dict__.get("community_used", {}).pop(k, None)
                overview.controller.last.pop("battery", None)
        elif a and key:
            a.undo(key)
        return web.json_response({"fixed": _fixed_lines(overview)})

    async def curtail_test(_req: web.Request) -> web.Response:
        """Settings -> Stop selling at negative prices -> Test (it runs up to 2 minutes; the page asks again)."""
        import asyncio

        cu = getattr(overview, "curtail", None)
        if not cu:
            return web.json_response({"error": "missing"}, status=404)
        if not cu.testing:
            asyncio.create_task(cu.test())
        return web.json_response({"ok": True})

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
        tl = getattr(overview, "timeline", None)
        diag["timeline"] = tl.last() if tl else []  # the last two days, every 5 minutes: to replay what happened
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
        notes = dict(overview.settings.get("report_notes") or {})
        if res.get("id") and payload["note"].strip():  # the question is shown above the answers
            notes[str(res["id"])] = payload["note"].strip()
        overview.save({"last_report": {"id": res.get("id"), "t": __import__("time").time()}, "replies": {},
                       "report_notes": dict(list(notes.items())[-10:])})
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
        from . import autoupdate

        auto = await autoupdate.state()
        return web.json_response({**tel.visible(mark_seen=True), "update": tel.update(), "whatsnew": tel.whatsnew(),
                                  "auto_update": None if overview.settings.get("autoupdate_no") else auto})

    async def replies_post(req: web.Request) -> web.Response:
        tel = getattr(overview, "telemetry", None)
        b = await req.json() if req.can_read_body else {}
        if tel and b.get("whatsnew_seen"):  # "OK" on "What's new"
            tel.whatsnew_seen()
            return web.json_response({"ok": True, "whatsnew": None})
        if b.get("auto_update") is True:  # "Update automatically" - Home Assistant's own switch for this app
            from . import autoupdate

            return web.json_response({"ok": await autoupdate.turn_on()})
        if b.get("auto_update") is False:  # "No thanks": the card doesn't come back
            overview.save({"autoupdate_no": True})
            return web.json_response({"ok": True})
        if tel and b.get("snooze"):  # "Later" on the update card: hidden for 7 days
            tel.snooze()
            return web.json_response({"ok": True, "update": tel.update()})
        if tel and b.get("hide"):  # "Close" on an answer - it comes back with a new comment
            tel.hide(str(b["hide"]))
            return web.json_response({"ok": True, "replies": tel.visible()})
        images = [{"name": str(i.get("name") or "picture")[:60], "data": i["data"]}
                  for i in (b.get("images") or [])[:3]
                  if isinstance(i, dict) and isinstance(i.get("data"), str) and len(i["data"]) <= 2_000_000]
        if not tel or not (str(b.get("text") or "").strip() or images):
            return web.json_response({"ok": False, "error": "content"}, status=400)
        res = await tel.write_back(b.get("id"), b.get("text"), images)
        return web.json_response({**res, "replies": tel.visible()}, status=200 if res.get("ok") else 502)

    app.router.add_post("/api/report", report)
    app.router.add_post("/api/curtail_test", curtail_test)
    app.router.add_get("/api/replies", replies_get)
    app.router.add_post("/api/replies", replies_post)
    app.router.add_get("/api/report", report_info)
    app.router.add_post("/api/autofix", autofix_post)
    app.router.add_get("/api/selftest", selftest_get)
    app.router.add_post("/api/selftest", selftest_post)
    app.router.add_get("/api/control", control_status)
    app.router.add_get("/api/entity_info", entity_info)
    app.router.add_post("/api/control", control_mode)
    app.router.add_post("/api/control/release", control_release)
    app.router.add_post("/api/trial", trial_post)
    app.router.add_post("/api/ev", ev)
    app.router.add_post("/api/charger", charger)
    app.router.add_post("/api/car_in", car_in)
    app.router.add_post("/api/things/arm", things_arm)
    app.router.add_post("/api/mode", mode)
    app.router.add_post("/api/shadow_all", stop_all)
    app.router.add_static("/static", FRONTEND)
    return app

"""Learning together: small anonymous lines that make Energy Pilot better for everyone - on unless the user turns it
off (Settings). Never names, places, entity names or use hour by hour.

Sent:
- once a day: version, Home Assistant version, country, language, which profile/charger/price source, what the house
  has (battery, car, solar …), Shadow/Control per part, days in shadow before control, saved this month (rounded),
  battery size (rounded), how well yesterday's forecasts hit, which features are on.
- after a self-test: the result per step, and what it mended (the option names the inverter itself offers).
- when something was mended by itself: only which kind (fuse, kW, price …).
- when the app itself fails: the kind of error and where in the code - once a day per error.

Answers from the developer: every hour, for 60 days after a "Get help" report or an app error was sent, the
developer's comments on it are fetched with this installation's own id and shown in the app (Settings); a new one
also gives a notification in Home Assistant - once per comment.

Fetched once a day: fixes that 3 installations with the same profile found - used here too (see control._fixed),
and how many have tested each profile.
"""

from __future__ import annotations

import asyncio
from datetime import date
import hashlib
import logging
import os
import time
import traceback
from typing import Any
import uuid

_LOGGER = logging.getLogger(__name__)
DAY_S = 24 * 3600
REPLY_DAYS = 60
FRESH_S = 7 * DAY_S  # asked every 10 minutes the first week after a report or an error, then hourly
CLOSED_KEEP_S = 7 * DAY_S  # an answer on a closed issue goes away a week after it was closed
SEEN_KEEP_S = 14 * DAY_S  # ... or two weeks after it was seen - a new comment brings it back
NEW_ANSWER = {
    "da": "💬 Ny besked fra udvikleren. Åbn Energipilot → Indstillinger for at læse den.",
    "en": "💬 New message from the developer. Open Energy Pilot → Settings to read it.",
    "de": "💬 Neue Nachricht vom Entwickler. Öffne Energy Pilot → Einstellungen, um sie zu lesen.",
    "fr": "💬 Nouveau message du développeur. Ouvrez Energy Pilot → Réglages pour le lire.",
    "nl": "💬 Nieuw bericht van de ontwikkelaar. Open Energy Pilot → Instellingen om het te lezen.",
    "sv": "💬 Nytt meddelande från utvecklaren. Öppna Energy Pilot → Inställningar för att läsa det.",
    "nb": "💬 Ny melding fra utvikleren. Åpne Energy Pilot → Innstillinger for å lese den.",
}


def _r(v: Any, step: float = 1.0) -> float | None:
    try:
        return round(round(float(v) / step) * step, 1)
    except (TypeError, ValueError):
        return None


class Telemetry:
    def __init__(self, overview: Any, url: str) -> None:
        self.ov, self.url = overview, url.rstrip("/") if url else ""
        self._errors_sent: dict[str, str] = {}
        if not self.ov.settings.get("install_id"):
            self.ov.save({"install_id": uuid.uuid4().hex, "first_seen": date.today().isoformat()})

    @property
    def on(self) -> bool:
        return bool(self.url) and self.ov.settings.get("share_anonymous", True) is not False

    # ---------- sending ----------
    async def _post(self, kind: str, payload: dict[str, Any]) -> bool:
        if not self.on:
            return False
        import aiohttp

        body = {"kind": kind, "install": self.ov.settings.get("install_id"), **payload}
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(f"{self.url}/t", json=body, headers={"x-ep-client": "energy-pilot"},
                                  timeout=aiohttp.ClientTimeout(total=20)) as r:
                    return r.status == 200
        except Exception:  # noqa: BLE001 - never in the way
            return False

    def event(self, kind: str, payload: dict[str, Any]) -> None:
        """Send in the background - never waits, never fails anything."""
        if not self.on:
            return
        try:
            asyncio.get_running_loop().create_task(self._post(kind, payload))
        except RuntimeError:
            pass

    # ---------- what is sent ----------
    def daily(self) -> dict[str, Any]:
        from . import mlcheck

        o, s = self.ov, self.ov.settings
        c = getattr(o, "controller", None)
        eng = getattr(o, "engine", None)
        f = o.flow() if hasattr(o, "flow") else {}
        modes = {p: c.mode(p) for p in c.parts()} if c else {}
        if any(m == "control" for m in modes.values()) and not s.get("first_control"):
            o.save({"first_control": date.today().isoformat()})
        try:
            days = (date.fromisoformat(s["first_control"]) - date.fromisoformat(s["first_seen"])).days if s.get("first_control") and s.get("first_seen") else None
        except ValueError:
            days = None
        src = str(o.source("price") or "") if hasattr(o, "source") else ""
        price = src.split(":", 1)[1] if src.startswith("integration:") else ("own" if eng and getattr(eng, "own_prices", None) and not o.role("price") else src or None)
        ledger, y, cap = {}, {}, None
        if eng:
            try:
                from datetime import datetime
                from zoneinfo import ZoneInfo

                ledger = eng.ledger.summary(datetime.now(ZoneInfo(o.ha.config.get("time_zone") or "UTC")))
                y = (eng.learning.summary() or {}).get("yesterday") or {}
                cap = eng.settings().capacity_kwh
            except Exception:  # noqa: BLE001
                pass
        has = (f.get("has") or {}) if isinstance(f, dict) else {}
        return {
            "version": os.environ.get("BUILD_VERSION", "dev"), "ha": str(o.ha.config.get("version") or "")[:12],
            "country": o.ha.config.get("country"), "currency": o.ha.config.get("currency"),
            "lang": s.get("language") or o.ha.config.get("language"),
            "profile": c.profile_key("battery") if c else None, "model": getattr(c, "model", None) if c else None,
            "charger": (c.platforms.get("car") if c else None), "price": price,
            "has": {"battery": bool(has.get("battery")), "car": bool(has.get("ev")), "pv": bool(has.get("pv")),
                    "things": bool(s.get("things")), "batteries": bool(s.get("batteries"))},
            "modes": modes, "days_to_control": days,
            "saved_month": _r(ledger.get("month"), 0.5), "battery_kwh": _r(cap, 0.5),
            "sun_err": _r(y.get("sun_err_ml") or y.get("sun_err_simple"), 0.01), "house_err": _r(y.get("house_err_ml") or y.get("house_error"), 0.01),
            "sun_source": getattr(o, "sun_source", None), "ml": mlcheck.why() or "ok",
            "features": {"export": bool(s.get("battery_export")), "targets": bool(s.get("battery_targets")), "things": bool(s.get("things")),
                         "power_tariff": bool(s.get("power_tariff_price")), "offgrid": bool(s.get("offgrid"))},
        }

    def test_result(self, results: list[dict[str, Any]]) -> None:
        c = getattr(self.ov, "controller", None)
        keep = ("part", "step", "result", "why", "option_from", "option_to")
        self.event("test", {"profile": c.profile_key("battery") if c else None, "model": getattr(c, "model", None) if c else None,
                            "charger": c.platforms.get("car") if c else None,
                            "results": [{k: r.get(k) for k in keep if r.get(k) is not None} for r in results]})

    def mended(self, key: str, what: str) -> None:
        self.event("autofix", {"key": f"{what}:{key.split(':', 1)[-1]}" if ":" in key else what})

    def error(self, record: logging.LogRecord) -> None:
        """The kind of error and where in Energy Pilot's own code - no message (it may hold entity names)."""
        if not record.exc_info or not record.exc_info[1]:
            return
        exc = record.exc_info[1]
        frames = [fr for fr in traceback.extract_tb(record.exc_info[2]) if "energy_pilot" in fr.filename]
        where = f"{os.path.basename(frames[-1].filename)}:{frames[-1].lineno} {frames[-1].name}" if frames else "?"
        text = f"{type(exc).__name__} at {where} ({record.name})"
        h = hashlib.sha1(text.encode()).hexdigest()[:16]
        today = date.today().isoformat()
        if self._errors_sent.get(h) == today:
            return
        self._errors_sent[h] = today
        if self.on:
            self.ov.save({"last_error": time.time()})  # a note from the developer may come back (fetch_answers)
        self.event("error", {"hash": h, "text": text, "version": os.environ.get("BUILD_VERSION", "dev")})

    # ---------- answers to "Get help" ----------
    async def _ask(self, path: str, body: dict[str, Any]) -> dict[str, Any] | None:
        import aiohttp

        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(f"{self.url}{path}", json={"install": self.ov.settings.get("install_id"), **body},
                                  headers={"x-ep-client": "energy-pilot"}, timeout=aiohttp.ClientTimeout(total=30)) as r:
                    d = await r.json(content_type=None)
                    return d if r.status == 200 else {"error": d.get("error") or f"http_{r.status}"}
        except Exception:  # noqa: BLE001
            return None

    def _last_sent(self) -> float:
        return max(float((self.ov.settings.get("last_report") or {}).get("t") or 0), float(self.ov.settings.get("last_error") or 0))

    def wants_answers(self) -> bool:
        return bool(self.url) and time.time() - self._last_sent() < REPLY_DAYS * DAY_S

    def answer_every(self) -> float | None:
        if self.wants_answers():
            return 600 if time.time() - self._last_sent() < FRESH_S else 3600
        return DAY_S if self.on else None  # an error sent by an older version

    @staticmethod
    def _key(r: dict[str, Any]) -> str:
        return str(r.get("id") or "e:" + hashlib.sha1(str(r.get("error")).encode()).hexdigest()[:12])

    @staticmethod
    def _newest(r: dict[str, Any]) -> str:
        return max((str(m.get("t") or "") for m in r.get("msgs") or [] if m.get("from") == "dev"), default="")

    def visible(self, mark_seen: bool = False) -> dict[str, Any]:
        """What the page shows: not the ones closed with "Close", a closed issue after a week, or one seen two weeks ago."""
        from datetime import datetime

        got = self.ov.settings.get("replies") or {}
        hidden = dict(self.ov.settings.get("replies_hidden") or {})
        shown = dict(self.ov.settings.get("replies_shown") or {})
        now, out, changed = time.time(), {"reports": [], "notes": [], "t": got.get("t")}, False
        for kind in ("reports", "notes"):
            for r in got.get(kind) or []:
                k, new = self._key(r), self._newest(r)
                if k in hidden and hidden[k] >= new:
                    continue
                closed = r.get("closed_at")
                try:
                    if closed and datetime.fromisoformat(str(closed).replace("Z", "+00:00")).timestamp() < now - CLOSED_KEEP_S and new <= closed:
                        continue
                except ValueError:
                    pass
                sh = shown.get(k)
                if new and sh and sh.get("t") == new and now - float(sh.get("at") or 0) > SEEN_KEEP_S:
                    continue
                if mark_seen and new and (not sh or sh.get("t") != new):
                    shown[k], changed = {"t": new, "at": now}, True
                out[kind].append({**r, "key": k})
        if changed:
            keep = {self._key(r) for kind in ("reports", "notes") for r in got.get(kind) or []}
            self.ov.save({"replies_shown": {k: v for k, v in shown.items() if k in keep}})
        return out

    def hide(self, key: str) -> None:
        got = self.ov.settings.get("replies") or {}
        r = next((x for kind in ("reports", "notes") for x in got.get(kind) or [] if self._key(x) == key), None)
        if r is not None:
            self.ov.save({"replies_hidden": {**(self.ov.settings.get("replies_hidden") or {}), key: self._newest(r)}})

    async def fetch_answers(self, notify: bool = True) -> dict[str, Any]:
        d = await self._ask("/replies", {})
        if not d or "reports" not in d:
            return self.ov.settings.get("replies") or {}
        got = {"reports": d["reports"][:5], "notes": (d.get("notes") or [])[:5], "t": time.time()}
        newest = max((str(m.get("t") or "") for r in got["reports"] + got["notes"] for m in r.get("msgs") or [] if m.get("from") == "dev"), default="")
        seen = self.ov.settings.get("replies_seen")
        seen = seen if isinstance(seen, str) else ""
        self.ov.save({"replies": got, "replies_seen": max(newest, seen)})
        if notify and newest > seen:  # once per new comment - closing the issue changes nothing
            lang = str(self.ov.settings.get("language") or self.ov.ha.config.get("language") or "en")[:2]
            try:
                await self.ov.ha.call_service("persistent_notification", "create", {
                    "notification_id": "energy_pilot_answer", "title": "Energy Pilot", "message": NEW_ANSWER.get(lang, NEW_ANSWER["en"])})
            except Exception:  # noqa: BLE001
                pass
        return got

    async def write_back(self, report_id: str, text: str) -> dict[str, Any]:
        d = await self._ask("/reply", {"id": str(report_id)[:40], "text": str(text)[:4000]})
        if d and d.get("ok"):
            await self.fetch_answers(notify=False)
            return {"ok": True}
        return {"ok": False, "error": (d or {}).get("error", "unreachable")}

    # ---------- the daily round ----------
    async def run(self) -> None:
        """Every 10 minutes: the daily line when a day has gone, and the shared fixes once a day."""
        while True:
            try:
                now = time.time()
                if self.on and now - float(self.ov.settings.get("telemetry_sent") or 0) >= DAY_S:
                    if await self._post("daily", {"data": self.daily()}):
                        self.ov.save({"telemetry_sent": now})
                if self.url and now - float((self.ov.settings.get("community") or {}).get("t") or 0) >= DAY_S:
                    await self.fetch_fixes()
                # every 10 minutes the first week after a report or an error, hourly until 60 days, then once a day
                every = self.answer_every()
                if every and now - float((self.ov.settings.get("replies") or {}).get("t") or 0) >= every:
                    await self.fetch_answers()
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Telemetry round failed", exc_info=True)
            await asyncio.sleep(600)

    async def fetch_fixes(self) -> None:
        import aiohttp

        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{self.url}/fixes", timeout=aiohttp.ClientTimeout(total=20)) as r:
                    if r.status != 200:
                        return
                    d = await r.json(content_type=None)
        except Exception:  # noqa: BLE001
            return
        self.ov.save({"community": {"fixes": (d.get("fixes") or [])[:500], "tested": d.get("tested") or {}, "t": time.time()}})


class ErrorHandler(logging.Handler):
    """Hands Energy Pilot's own errors (with a traceback) to telemetry."""

    def __init__(self, telemetry: Telemetry) -> None:
        super().__init__(level=logging.WARNING)
        self.t = telemetry

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.t.error(record)
        except Exception:  # noqa: BLE001
            pass

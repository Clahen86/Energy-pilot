"""Ready to take over? - and "Try control for 24 hours".

After three days in shadow with the self-test passed, the panel asks once: here is what it would have saved, try it
for a day? One tap puts the battery parts in control; after 24 hours they go back to shadow by themselves - also after
a restart, as the end time is kept in the settings - and the panel says what the day saved. "Everything to shadow"
ends it at once, as always.
"""

from __future__ import annotations

from datetime import date, datetime
import time
from typing import Any

TRIAL_H = 24
READY_DAYS = 3
ASK_AGAIN_DAYS = 7  # "Not now": asked again after a week


def _days_since(first: str | None, now: datetime) -> int:
    try:
        return (now.date() - date.fromisoformat(str(first))).days
    except ValueError:
        return 0


def _parts(c: Any) -> list[str]:
    return [p for p in ["battery", *c.bat_parts()] if not c.blocked(p)]


def ready(ov: Any, tested: str | None, now: datetime) -> dict[str, Any] | None:
    """The question to show, or None: battery in shadow and controllable, self-test passed, 3 days seen."""
    s, c = ov.settings, getattr(ov, "controller", None)
    if not c or s.get("trial") or tested not in ("ok", "fixed"):
        return None
    parts = _parts(c)
    if not parts or any(c.mode(p) != "shadow" for p in parts):
        return None  # already controlling (or switched off): nothing to ask
    if _days_since(s.get("first_seen"), now) < READY_DAYS:
        return None
    if time.time() - float(s.get("ready_no") or 0) < ASK_AGAIN_DAYS * 86400:
        return None
    eng = getattr(ov, "engine", None)
    pilot = None
    try:
        pilot = (eng.ledger.summary(now).get("pilot") or {}).get("month") if eng else None
    except Exception:  # noqa: BLE001
        pilot = None
    retro = eng.retro_shown() if eng and hasattr(eng, "retro_shown") else None
    return {"saved": pilot if pilot and pilot > 0 else None, "per_month": (retro or {}).get("per_month")}


def start(ov: Any, now: datetime) -> bool:
    c = getattr(ov, "controller", None)
    if not c:
        return False
    parts = [p for p in _parts(c) if c.mode(p) == "shadow"]
    if not parts:
        return False
    eng = getattr(ov, "engine", None)
    try:
        at = (eng.ledger.summary(now).get("pilot") or {}).get("total") or 0.0
    except Exception:  # noqa: BLE001
        at = 0.0
    ov.save({"trial": {"until": time.time() + TRIAL_H * 3600, "parts": parts, "pilot_at": at}})
    for p in parts:
        c.set_mode(p, "control")
    return True


async def end(ov: Any, now: datetime) -> None:
    """Back to shadow (the trial's own parts only) and what the day saved kept for the panel."""
    t, c = ov.settings.get("trial") or {}, getattr(ov, "controller", None)
    if not t or not c:
        return
    for p in t.get("parts") or []:
        if c.mode(p) == "control":
            await c.hand_back(p)
            c.set_mode(p, "shadow")
    eng = getattr(ov, "engine", None)
    try:
        total = (eng.ledger.summary(now).get("pilot") or {}).get("total") or 0.0
    except Exception:  # noqa: BLE001
        total = None
    saved = round(total - float(t.get("pilot_at") or 0.0), 2) if total is not None else None
    ov.save({"trial": None, "trial_done": {"t": time.time(), "saved": saved, "parts": t.get("parts") or []}, "trial_done_seen": False})


async def tick(ov: Any, now: datetime) -> None:
    t = ov.settings.get("trial") or {}
    if t and time.time() >= float(t.get("until") or 0):
        await end(ov, now)


def view(ov: Any, tested: str | None, now: datetime) -> dict[str, Any] | None:
    """For the panel: a trial running (hours left), just done (what it saved, a week), or the question."""
    s = ov.settings
    if t := s.get("trial"):
        return {"running": True, "hours_left": max(0, round((float(t.get("until") or 0) - time.time()) / 3600))}
    done = s.get("trial_done") or {}
    if done and time.time() - float(done.get("t") or 0) < 7 * 86400 and not s.get("trial_done_seen"):
        return {"done": True, "saved": done.get("saved")}
    q = ready(ov, tested, now)
    return {"ask": True, **q} if q else None

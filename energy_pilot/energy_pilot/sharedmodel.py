"""The shared house model: trained every night on all houses that share their hours (training/train.py), and handed out
only when it clearly beat the houses' own forecasts on days it hadn't seen. It is plain arrays of trees (JSON) - walked
here in plain Python, never unpickled - and checked against its own sample answers before it is used.

It is the third forecast of the house in the blend (blend.Mixer): it gets no say in a home until it has hit well there for
three weeks, and loses it again by itself if it misses. Nothing to set: no model (or COMMON_OFF) is the old two-way blend.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)
FILE = "energy_pilot_common_house.json"
FEATURES = ["h", "weekday", "month", "country", "battery_kwh", "car", "prev", "week"]
MAX_BYTES = 400_000


def predict(m: dict[str, Any], x: list[Any]) -> float:
    """Sum of the trees' leaves, as scikit-learn's HistGradientBoosting does: left when x <= threshold, missing as told."""
    out = float(m["base"])
    for t in m["trees"]:
        i = 0
        while not t["leaf"][i]:
            v = x[t["f"][i]]
            left = bool(t["m"][i]) if v is None or v != v else v <= t["t"][i]
            i = t["l"][i] if left else t["r"][i]
        out += t["v"][i]
    return out


def check(body: bytes, want_sha: str | None) -> dict[str, Any] | None:
    """The model as downloaded - only if it is what the worker named, in the shape this version knows, and it gives its
    own sample answers."""
    if len(body) > MAX_BYTES or (want_sha and hashlib.sha256(body).hexdigest() != want_sha):
        return None
    try:
        m = json.loads(body)
    except ValueError:
        return None
    if not isinstance(m, dict) or m.get("schema") != 1 or m.get("features") != FEATURES or not isinstance(m.get("trees"), list):
        return None
    try:
        if not m.get("probe") or any(abs(predict(m, x) - y) > 1e-3 for x, y in m["probe"]):
            return None
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    return m


def load(folder: Path) -> dict[str, Any] | None:
    try:
        return check((folder / FILE).read_bytes(), None)
    except OSError:
        return None


def house(m: dict[str, Any] | None, real: dict[datetime, float], times: list[datetime], country: str | None,
          battery_kwh: float | None, car: bool) -> list[float | None]:
    """kWh per coming hour from the shared model, with this home's own recent hours as its level. None where it can't
    say (a country it wasn't trained on, no history for that hour)."""
    if not m or not real:
        return [None] * len(times)
    countries = m.get("countries") or []
    if (country or "?") not in countries:
        return [None] * len(times)
    ci = countries.index(country or "?")
    by = {(t.date(), t.hour): kw for t, kw in real.items() if kw is not None and 0 <= kw <= 50}
    newest = max(t.date() for t in real)
    top = max(by.values()) if by else 0.0
    cap = round(float(battery_kwh or 0) * 2) / 2
    out: list[float | None] = []
    for t in times:
        d = t.date()
        # yesterday's same hour - for hours further ahead than the newest known day, the newest day that has it
        prev = by.get((d - timedelta(days=1), t.hour))
        back = 1
        while prev is None and back < 4:
            back += 1
            prev = by.get((min(d, newest + timedelta(days=1)) - timedelta(days=back), t.hour))
        base = min(d, newest + timedelta(days=1))
        week = [by.get((base - timedelta(days=i), t.hour)) for i in range(1, 8)]
        week = [w for w in week if w is not None]
        if prev is None or not week:
            out.append(None)
            continue
        try:
            v = predict(m, [t.hour, t.weekday(), t.month, ci, cap, 1.0 if car else 0.0, prev, sum(week) / len(week)])
        except (KeyError, IndexError, TypeError):
            out.append(None)
            continue
        out.append(round(min(max(0.0, v), (m.get("clip") or 1.5) * top), 3) if top else None)
    return out


async def refresh(session: Any, url: str, folder: Path, descriptor: dict[str, Any] | None) -> None:
    """Fetched once per version (the worker names it by its sha in the daily /fixes); gone again when the worker stops
    naming one (not good enough any more, or COMMON_OFF)."""
    path = folder / FILE
    want = (descriptor or {}).get("v") if isinstance(descriptor, dict) else None
    if not want:
        try:
            path.unlink()
        except OSError:
            pass
        return
    try:
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == want:
            return
    except OSError:
        pass
    import aiohttp

    try:
        async with session.get(f"{url}/model/house", timeout=aiohttp.ClientTimeout(total=30)) as r:
            if r.status != 200:
                return
            body = await r.read()
    except Exception:  # noqa: BLE001
        return
    if check(body, want) is None:
        _LOGGER.info("Shared house model refused (not what the worker named, or it doesn't give its own answers)")
        return
    try:
        path.write_bytes(body)
        _LOGGER.info("Shared house model %s fetched", want[:12])
    except OSError:
        pass

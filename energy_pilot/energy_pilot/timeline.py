"""The last two days, every 5 minutes: what Energy Pilot saw, planned and did - sent with a report, so a problem can
be replayed afterwards (the car charging at the dear hour, say). Small (about 100 KB) and kept on disk over restarts.
Only numbers and modes - no names."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from collections import deque
from pathlib import Path
import time
from typing import Any

KEEP = 48 * 12  # two days of 5-minute rounds
SAVE_EVERY = 1800


def _r(v: Any) -> Any:
    return round(v, 2) if isinstance(v, float) else v


def snapshot(ov: Any, eng: Any, ctl: Any) -> dict[str, Any]:
    """One round: the flows, this slot's price and forecast, the plan's choice and what each part was told."""
    f = ov.flow() or {}
    res = (eng.result if eng else None) or {}
    b, car = res.get("battery") or {}, res.get("car") or {}
    row: dict[str, Any] = {"t": int(time.time())}
    row.update({k: _r(f.get(k)) for k in ("pv", "house", "battery", "soc", "grid", "ev", "plug") if f.get(k) is not None})
    row.update({k: _r(v) for k, v in (getattr(eng, "now_slot", None) or {}).items()})
    if b:
        row["plan"] = b.get("now")
        row["target"] = _r(b.get("target"))
    if car:
        try:
            row["car_plan"] = bool(car.get("hours")) and datetime.fromisoformat(car["hours"][0]) <= datetime.now(timezone.utc)
        except (TypeError, ValueError):
            pass
    if ctl:
        try:
            wants = ctl.intents()
        except Exception:  # noqa: BLE001 - the timeline never stops a round
            wants = {}
        row["do"] = {p: [ctl.mode(p), (w or {}).get("intent")] for p, w in wants.items() if w}
        if getattr(ctl, "car_why", ""):
            row["car_why"] = ctl.car_why
    return row


class Timeline:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.rows: deque = deque(maxlen=KEEP)
        self._saved = time.time()
        try:
            for line in path.read_text(errors="replace").splitlines()[-KEEP:]:
                try:
                    self.rows.append(json.loads(line))
                except ValueError:
                    continue  # a broken line (the power went mid-write): skipped, the rest kept
        except OSError:
            pass

    def add(self, row: dict[str, Any]) -> None:
        self.rows.append(row)
        if time.time() - self._saved > SAVE_EVERY:
            self.save()

    def save(self) -> None:
        self._saved = time.time()
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text("\n".join(json.dumps(r, separators=(",", ":")) for r in self.rows))
            tmp.replace(self.path)
        except OSError:
            pass

    def last(self, hours: float = 48) -> list[dict[str, Any]]:
        since = time.time() - hours * 3600
        return [r for r in self.rows if r.get("t", 0) >= since]

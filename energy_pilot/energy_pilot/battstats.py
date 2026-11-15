"""The battery's own story, measured every half minute: the level hour by hour for the week that went, the longest
time the house went without buying from the grid, and how many evenings in a row the battery lasted.

Only what was really seen counts - a gap (a restart) ends a run rather than bridging it.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

BUY_W = 80  # buying less than this counts as "without the grid" (meters drift a little)
BLIP_S = 120  # the kettle may pull from the grid this long without ending a run
GAP_S = 300  # a longer gap between readings (a restart) ends a run
EVENING = range(17, 22)  # the evening the battery should last through


class BattStats:
    def __init__(self, data_dir: Path) -> None:
        self.file = data_dir / "energy_pilot_battstats.json"
        self.state: dict[str, Any] = {"hours": {}, "best": None, "evenings": {}}
        try:
            self.state.update(json.loads(self.file.read_text()))
        except (OSError, ValueError):
            pass
        self._at: datetime | None = None
        self._run_from: datetime | None = None
        self._buy_since: datetime | None = None
        self._saved = 0.0

    def save(self) -> None:
        try:
            self.file.write_text(json.dumps(self.state))
        except OSError:
            pass

    def tick(self, now: datetime, flow: dict[str, Any], min_soc: float) -> None:
        prev, self._at = self._at, now
        s, soc, grid = self.state, flow.get("soc"), flow.get("grid")
        if soc is not None:
            k = now.strftime("%Y-%m-%dT%H")
            a = s["hours"].setdefault(k, [0.0, 0])
            a[0] += float(soc)
            a[1] += 1
            day = now.date().isoformat()
            if now.hour in EVENING and float(soc) <= min_soc + 1:
                s["evenings"][day] = False  # ran out this evening
            elif now.hour >= EVENING.stop and day not in s["evenings"]:
                s["evenings"][day] = True
        if prev is None or (now - prev).total_seconds() > GAP_S:
            self._run_from = self._buy_since = None
        if grid is not None:
            if float(grid) <= BUY_W:
                self._buy_since = None
                self._run_from = self._run_from or now
            else:
                self._buy_since = self._buy_since or now
                if (now - self._buy_since).total_seconds() > BLIP_S:
                    self._run_from = None
            if self._run_from:
                h = (now - self._run_from).total_seconds() / 3600
                best = s.get("best") or {}
                if h >= 0.5 and h > (best.get("h") or 0):
                    s["best"] = {"h": round(h, 2), "day": self._run_from.date().isoformat()}
        if now.timestamp() - self._saved > 300:
            cut = (now - timedelta(days=8)).strftime("%Y-%m-%dT%H")
            s["hours"] = {k: v for k, v in s["hours"].items() if k >= cut}
            dcut = (now - timedelta(days=60)).date().isoformat()
            s["evenings"] = {k: v for k, v in s["evenings"].items() if k >= dcut}
            self.save()
            self._saved = now.timestamp()

    def streak(self, now: datetime) -> int:
        ev, n = self.state["evenings"], 0
        day = now.date() if now.date().isoformat() in ev else now.date() - timedelta(days=1)
        while ev.get(day.isoformat()) is True:
            n += 1
            day -= timedelta(days=1)
        return n

    def summary(self, now: datetime, min_soc: float) -> dict[str, Any]:
        hours = self.state["hours"]
        week, days = [], []
        for back in range(6, -1, -1):
            d = (now - timedelta(days=back)).date()
            row = []
            for h in range(24):
                v = hours.get(f"{d.isoformat()}T{h:02d}")
                row.append(round(v[0] / v[1]) if v and v[1] else None)
            week.append(row)
            days.append(d.isoformat())
        # a tip from the week: empty most evenings - or never close to it
        full_days = [r for r in week[:-1] if sum(v is not None for v in r) >= 20]
        empties = [next((h for h in range(15, 24) if r[h] is not None and r[h] <= min_soc + 2), None) for r in full_days]
        hit = sorted(h for h in empties if h is not None)
        tip = None
        if len(full_days) >= 4 and len(hit) >= max(3, len(full_days) * 0.6):
            tip = {"kind": "empty_evenings", "from": hit[len(hit) // 2]}
        elif len(full_days) >= 5 and all(min(v for v in r if v is not None) > min_soc + 15 for r in full_days):
            tip = {"kind": "never_low"}
        best = self.state.get("best")
        return {"week": week, "days": days, "best": best, "streak": self.streak(now), "tip": tip,
                "has_week": len(full_days) >= 2}

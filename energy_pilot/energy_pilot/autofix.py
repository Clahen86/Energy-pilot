"""Mistakes Energy Pilot mends by itself - only ones that can't cost money or harm anything: they change how a value
is read, or make Energy Pilot more careful. Each is shown as one line with an undo.

- The main fuse written in amps (75) where kW was asked: set to what that fuse carries (a bit under, to be safe).
- A battery level given as 0-1 instead of 0-100.
- A power sensor in kW without saying so (3.2 where 3200 W was meant).
- A price in øre/cents instead of kroner/euros.
- A chosen sensor that disappeared (an integration renamed it): the one found in its place is used.
- A chosen grid or house power sensor stuck for hours, or unavailable: another that works is used.

Anything that steers the inverter or the charger is never changed here.
"""

from __future__ import annotations

from collections import deque
import statistics
import time
from typing import Any

POWER_ROLES = ("pv_power", "battery_power", "grid_power", "house_power", "ev_power")
STUCK_ROLES = ("grid_power", "house_power")  # these never sit still for hours in a lived-in house
ONE_PHASE = {"GB", "IE", "US", "CA", "AU", "NZ", "JP", "MX", "PH"}  # houses mostly on one phase
STUCK_S = 6 * 3600
GONE_S = 30 * 60


def _f(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class AutoFix:
    def __init__(self, overview: Any) -> None:
        self.ov = overview
        self.samples: dict[str, deque] = {}
        self.gone_since: dict[str, float] = {}

    @property
    def log(self) -> list[dict[str, Any]]:
        return list(self.ov.settings.get("autofix_log") or [])

    def _ignored(self, key: str) -> bool:
        return key in (self.ov.settings.get("autofix_ignore") or [])

    def _done(self, key: str, what: str, old: Any, new: Any, change: dict[str, Any]) -> None:
        entry = {"key": key, "what": what, "from": old, "to": new, "t": time.time()}
        self.ov.save({**change, "autofix_log": ([e for e in self.log if e["key"] != key] + [entry])[-20:]})

    def undo(self, key: str) -> None:
        e = next((x for x in self.log if x["key"] == key), None)
        if not e:
            return
        s = self.ov.settings
        change: dict[str, Any] = {}
        if e["what"] == "fuse":
            change["import_limit_kw"] = e["from"]
        elif e["what"] in ("soc_scale", "kw_scale"):
            role = key.split(":", 1)[1]
            change["role_scale"] = {k: v for k, v in (s.get("role_scale") or {}).items() if k != role}
        elif e["what"] == "price_scale":
            change["price_scale"] = None
        elif e["what"] in ("renamed", "stuck"):
            role = key.split(":", 1)[1]
            change["roles"] = {**(s.get("roles") or {}), role: e["from"]}
        self.ov.save({**change, "autofix_log": [x for x in self.log if x["key"] != key],
                      "autofix_ignore": list(dict.fromkeys((s.get("autofix_ignore") or []) + [key]))})

    # ---------- every minute ----------
    def run(self) -> None:
        st = self.ov.ha.states
        now = time.time()
        roles = self.ov.roles()
        for r in POWER_ROLES + ("battery_soc",):
            v = _f((st.get(roles.get(r) or "") or {}).get("state"))
            if v is not None:
                self.samples.setdefault(r, deque(maxlen=90)).append(v)
        self.fuse()
        self.soc_scale(roles)
        self.kw_scale(roles)
        self.price_scale()
        self.renamed(st, now)
        self.stuck(st, roles, now)

    def fuse(self) -> None:
        v = _f(self.ov.settings.get("import_limit_kw"))
        if v is None or v <= 50 or self._ignored("fuse"):
            return
        country = str(self.ov.ha.config.get("country") or "").upper()
        phases = 1 if country in ONE_PHASE else 3
        kw = max(3, round(v * 0.23 * phases * 0.92))  # amps × 230 V × phases, a little under the fuse
        self._done("fuse", "fuse", v, kw, {"import_limit_kw": kw})

    def soc_scale(self, roles: dict[str, Any]) -> None:
        key = "soc:battery_soc"
        s = self.samples.get("battery_soc") or []
        if len(s) < 30 or self._ignored(key) or (self.ov.settings.get("role_scale") or {}).get("battery_soc"):
            return
        if max(s) <= 1.0 and any(0.02 < x < 0.98 for x in s):
            self._done(key, "soc_scale", 1, 100, {"role_scale": {**(self.ov.settings.get("role_scale") or {}), "battery_soc": 100}})

    def kw_scale(self, roles: dict[str, Any]) -> None:
        """A power sensor whose numbers are kW-sized while the others are in watts, and that doesn't say kW."""
        scale = self.ov.settings.get("role_scale") or {}
        big = [r for r in POWER_ROLES if (s := self.samples.get(r)) and len(s) >= 30 and max(abs(x) for x in s) > 300]
        if not big:
            return
        for r in POWER_ROLES:
            key = f"kw:{r}"
            s = self.samples.get(r) or []
            e = roles.get(r)
            unit = str(((self.ov.ha.states.get(e or "") or {}).get("attributes") or {}).get("unit_of_measurement") or "").lower()
            if len(s) < 60 or r in big or scale.get(r) or self._ignored(key) or unit == "kw":
                continue
            moving = [x for x in s if abs(x) >= 0.2]
            if len(moving) >= 20 and max(abs(x) for x in s) <= 30 and any(abs(x - round(x)) > 0.01 for x in moving):
                self._done(key, "kw_scale", 1, 1000, {"role_scale": {**scale, r: 1000}})

    def price_scale(self) -> None:
        key = "price"
        if self._ignored(key) or self.ov.settings.get("price_scale"):
            return
        prices = list((getattr(self.ov, "fine_prices", None) or {}).values())
        if len(prices) < 12:
            return
        cur = str(self.ov.ha.config.get("currency") or "").upper()
        limit = 20 if cur in ("DKK", "SEK", "NOK") else 5  # never seen in a whole day of real prices
        if statistics.median(prices) > limit:
            self._done(key, "price_scale", 1, 0.01, {"price_scale": 0.01})

    def renamed(self, st: dict[str, Any], now: float) -> None:
        chosen = self.ov.settings.get("roles") or {}
        for role, e in chosen.items():
            if not isinstance(e, str) or not e or e in st:
                self.gone_since.pop(f"renamed:{role}", None)
                continue
            key = f"renamed:{role}"
            since = self.gone_since.setdefault(key, now)
            found = self.ov.role(role)  # the one found in its place
            if now - since >= GONE_S and found and found != e and not self._ignored(key):
                self._done(key, "renamed", e, found, {"roles": {**chosen, role: found}})

    def stuck(self, st: dict[str, Any], roles: dict[str, Any], now: float) -> None:
        from datetime import datetime

        chosen = self.ov.settings.get("roles") or {}
        for role in STUCK_ROLES:
            e = roles.get(role)
            key = f"stuck:{role}"
            if not e or self._ignored(key) or chosen.get(role) != e:
                continue  # only the user's own choice is swapped - a found one changes by itself
            s = st.get(e) or {}
            try:
                age = now - datetime.fromisoformat(str(s.get("last_changed"))).timestamp()
            except ValueError:
                continue
            bad = s.get("state") in ("unavailable", "unknown") and age > GONE_S or age > STUCK_S
            if not bad:
                continue
            alt = self._alternative(role, e, st, now)
            if alt:
                self._done(key, "stuck", e, alt, {"roles": {**chosen, role: alt}})

    def _alternative(self, role: str, bad: str, st: dict[str, Any], now: float) -> str | None:
        from datetime import datetime

        for c in (self.ov.candidates().get(role) or []):
            e = c.get("entity_id")
            if not e or e == bad or not c.get("guess"):
                continue
            s = st.get(e) or {}
            try:
                fresh = now - datetime.fromisoformat(str(s.get("last_changed"))).timestamp() < 3600
            except ValueError:
                continue
            if fresh and _f(s.get("state")) is not None:
                return e
        return None

    def lines(self) -> list[dict[str, Any]]:
        """For the page: what was mended, newest first."""
        return sorted(self.log, key=lambda e: -e["t"])

"""Mistakes Energy Pilot mends by itself - only ones that can't cost money or harm anything: they change how a value
is read, or make Energy Pilot more careful. Each is shown as one line with an undo.

- The main fuse written in amps (75) where kW was asked: set to what that fuse carries (a bit under, to be safe).
- A battery level given as 0-1 instead of 0-100.
- A power sensor in kW without saying so (3.2 where 3200 W was meant).
- A price in øre/cents instead of kroner/euros.
- A chosen sensor that disappeared (an integration renamed it): the one found in its place is used.
- A chosen grid or house power sensor stuck for hours, or unavailable: another that works is used.
- A chosen battery level, battery power or solar sensor unavailable for half an hour: another that works is used.
- The meters don't add up (sun + grid = house + battery) for two hours: the one sensor that makes them add up is
  used instead - the house taken from the grid's sensor (Fox ESS), a battery or grid read the wrong way round.

Anything that steers the inverter or the charger is never changed here.
"""

from __future__ import annotations

import re

from collections import deque
import statistics
import time
from typing import Any

POWER_ROLES = ("pv_power", "battery_power", "grid_power", "house_power", "ev_power")
# A meter for one phase only (Deye "Load L1 Power", "phase_a") - never taken for the whole house or grid.
PHASE_METER = re.compile(r"(^|[\s_.-])(l[123]|phase[\s_-]?[abc123])([\s_-]|$)", re.I)
STUCK_ROLES = ("grid_power", "house_power")  # these never sit still for hours in a lived-in house
GONE_ROLES = ("battery_soc", "battery_power", "pv_power")  # may sit still (night, idle) - only "unavailable" counts
ONE_PHASE = {"GB", "IE", "US", "CA", "AU", "NZ", "JP", "MX", "PH"}  # houses mostly on one phase
STUCK_S = 6 * 3600
GONE_S = 30 * 60
BAL_ROLES = ("house_power", "grid_power", "battery_power", "pv_power")
BAL_KEY = {"house_power": "house", "grid_power": "grid", "battery_power": "batt", "pv_power": "pv"}
BAL_NEED = 60  # minutes with something happening before the meters are judged
BAL_EVERY = 600


def _tol(s: dict[str, Any]) -> float:
    """What the meters may miss by: the inverter's own losses and sensors read a moment apart."""
    return 0.15 * max(abs(s["pv"]), abs(s["grid"]), abs(s["batt"]), abs(s["house"])) + 120


def _expected(key: str, s: dict[str, Any]) -> float:
    """What one meter should show for sun + grid = house + battery (charging +) to hold."""
    return {"house": s["pv"] + s["grid"] - s["batt"], "grid": s["house"] + s["batt"] - s["pv"],
            "batt": s["pv"] + s["grid"] - s["house"], "pv": s["house"] + s["batt"] - s["grid"]}[key]


def judge(samples: list[dict[str, Any]], cands: dict[str, list[str]], signable: set[str]) -> dict[str, Any]:
    """Do the meters add up? {"ok": None} too little seen, {"ok": True}, or {"ok": False, "fix": {...}} with the one
    change that makes them add up: another sensor for a part, or a part read the other way round. Only a change that
    holds in nearly every minute, and also when that part shows a lot - a sensor sitting at 0 fits a quiet grid."""
    use = [s for s in samples if max(abs(s["pv"]), abs(s["grid"]), abs(s["batt"]), abs(s["house"])) >= 250]
    if len(use) < BAL_NEED * 2 // 3:
        return {"ok": None}
    off = sum(abs(s["pv"] + s["grid"] - s["batt"] - s["house"]) > _tol(s) for s in use) / len(use)
    if off < 0.5:
        return {"ok": True, "off": round(off, 2)}
    best = None
    for role in BAL_ROLES:
        key = BAL_KEY[role]
        options = [("sign", None)] if role in signable else []
        options += [("entity", e) for e in cands.get(role, [])]
        for kind, e in options:
            n = hits = big = big_hits = 0
            for s in use:
                v = -s[key] if kind == "sign" else (s.get("c") or {}).get(e)
                if v is None:
                    continue
                exp = _expected(key, s)
                ok = abs(v - exp) <= _tol(s)
                n, hits = n + 1, hits + ok
                if abs(exp) >= 300:
                    big, big_hits = big + 1, big_hits + ok
            if n < 0.8 * len(use) or big < 10 or hits / n < 0.85 or big_hits / big < 0.85:
                continue
            if best is None or hits / n > best[0]:
                best = (hits / n, role, kind, e)
    out: dict[str, Any] = {"ok": False, "off": round(off, 2)}
    if best:
        out["fix"] = {"role": best[1], "kind": best[2], "entity": best[3], "share": round(best[0], 2)}
    return out


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
        self.bal: deque = deque(maxlen=120)  # two hours of minutes: the meters and the other sensors that could be them
        self.bal_at = time.time()
        self.balance_state: dict[str, Any] = {"ok": None}

    @property
    def log(self) -> list[dict[str, Any]]:
        return list(self.ov.settings.get("autofix_log") or [])

    def _ignored(self, key: str) -> bool:
        return key in (self.ov.settings.get("autofix_ignore") or [])

    def _done(self, key: str, what: str, old: Any, new: Any, change: dict[str, Any]) -> None:
        entry = {"key": key, "what": what, "from": old, "to": new, "t": time.time()}
        self.ov.save({**change, "autofix_log": ([e for e in self.log if e["key"] != key] + [entry])[-20:]})
        tel = getattr(self.ov, "telemetry", None)
        if tel:
            tel.mended(key, what)

    def undo(self, key: str) -> None:
        e = next((x for x in self.log if x["key"] == key), None)
        if not e:
            return
        s = self.ov.settings
        change: dict[str, Any] = {}
        if e["what"] in ("fuse", "fuse_inv"):
            change["import_limit_kw"] = e["from"]
        elif e["what"] in ("soc_scale", "kw_scale"):
            role = key.split(":", 1)[1]
            change["role_scale"] = {k: v for k, v in (s.get("role_scale") or {}).items() if k != role}
        elif e["what"] == "price_scale":
            change["price_scale"] = None
        elif e["what"] in ("renamed", "stuck", "gone", "balance"):
            role = key.split(":", 1)[1]
            change["roles"] = {**(s.get("roles") or {}), role: e["from"]}
        elif e["what"] == "balance_sign":
            role = key.split(":", 1)[1]
            change["grid_sign" if role == "grid_power" else "battery_sign"] = e["from"]
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
        self.fuse_inverter()
        self.soc_scale(roles)
        self.kw_scale(roles)
        self.price_scale()
        self.renamed(st, now)
        self.stuck(st, roles, now)
        self.gone(st, roles, now)
        self.balance(st, roles, now)

    def _phases(self) -> int:
        return 1 if str(self.ov.ha.config.get("country") or "").upper() in ONE_PHASE else 3

    def fuse(self) -> None:
        v = _f(self.ov.settings.get("import_limit_kw"))
        if v is None or v <= 50 or self._ignored("fuse"):
            return
        country = str(self.ov.ha.config.get("country") or "").upper()
        phases = 1 if country in ONE_PHASE else 3
        kw = max(3, round(v * 0.23 * phases * 0.92))  # amps × 230 V × phases, a little under the fuse
        self._done("fuse", "fuse", v, kw, {"import_limit_kw": kw})

    def fuse_inverter(self) -> None:
        """The inverter's integration knows the main fuse (Kostal's House Fuse Size): the import limit is set from it
        while it is still the 10 kW new installs start with - or what this set last time, so a fuse changed there
        follows. A limit the user typed (or took away) is never touched."""
        key = "fuse_inverter"
        ctl = getattr(self.ov, "controller", None)
        if ctl is None or not hasattr(ctl, "fuse_amps") or self._ignored(key):
            return
        try:
            amps = ctl.fuse_amps()
        except Exception:  # not discovered yet
            return
        if not amps:
            return
        kw = max(3, round(amps * 0.23 * self._phases() * 0.92))  # amps × 230 V × phases, a little under the fuse
        s = self.ov.settings
        cur = _f(s.get("import_limit_kw"))
        last = next((e for e in self.log if e["key"] == key), None)
        ours = last is not None and cur == _f(last["to"])
        if cur == kw or not (ours or cur == 10 and not s.get("fuse_ok")):
            return
        self._done(key, "fuse_inv", last["from"] if ours else cur, kw, {"import_limit_kw": kw})

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
        # Taken for kW, but now it reads hundreds: it was watts all along (an idle battery's few watts looked like kW).
        # Put back at once, and never again for that sensor.
        for r, k in list(scale.items()):
            s = self.samples.get(r) or []
            if r in POWER_ROLES and k == 1000 and s and max(abs(x) for x in s) > 300:
                self.undo(f"kw:{r}")
                scale = self.ov.settings.get("role_scale") or {}
        big = [r for r in POWER_ROLES if (s := self.samples.get(r)) and len(s) >= 30 and max(abs(x) for x in s) > 300]
        if not big:
            return
        for r in POWER_ROLES:
            key = f"kw:{r}"
            s = self.samples.get(r) or []
            e = roles.get(r)
            unit = str(((self.ov.ha.states.get(e or "") or {}).get("attributes") or {}).get("unit_of_measurement") or "").lower()
            # Only a sensor that gives no unit: one that says W is taken at its word (an idle battery shows a few watts).
            if len(s) < 60 or r in big or scale.get(r) or self._ignored(key) or unit in ("w", "kw", "kwh", "wh"):
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

    def gone(self, st: dict[str, Any], roles: dict[str, Any], now: float) -> None:
        """The user's own battery level, battery power or solar sensor unavailable for half an hour while another that
        works was found: that one is used (the old one comes back with undo)."""
        chosen = self.ov.settings.get("roles") or {}
        for role in GONE_ROLES:
            e = roles.get(role)
            key = f"gone:{role}"
            if not e or self._ignored(key) or chosen.get(role) != e:
                continue
            s = st.get(e)
            if not s or s.get("state") not in ("unavailable", "unknown"):
                self.gone_since.pop(key, None)
                continue
            since = self.gone_since.setdefault(key, now)
            if now - since < GONE_S:
                continue
            alt = self._alternative(role, e, st, now)
            if alt:
                self._done(key, "gone", e, alt, {"roles": {**chosen, role: alt}})

    def _bal_cands(self, roles: dict[str, Any]) -> dict[str, list[str]]:
        """The sensors that could stand in for each part: named for it, able to be it, not one phase of three."""
        from .detect import fits_role

        st, out = self.ov.ha.states, {}
        for role in BAL_ROLES:
            got = []
            for c in (self.ov.candidates().get(role) or []):
                e = c.get("entity_id")
                if not e or e == roles.get(role) or not c.get("guess"):
                    continue
                a = (st.get(e) or {}).get("attributes") or {}
                if not fits_role(role, e, a, None) or (self._phases() == 3 and (PHASE_METER.search(e) or PHASE_METER.search(str(a.get("friendly_name") or "")))):
                    continue
                got.append(e)
            out[role] = got[:12]
        return out

    def balance(self, st: dict[str, Any], roles: dict[str, Any], now: float) -> None:
        """Every minute the meters are put side by side; every 10 minutes, with two hours seen, judged (judge())."""
        from .overview import _watts

        if not callable(getattr(self.ov, "flow", None)):
            return
        f = self.ov.flow() or {}
        pv, grid, house, ev = f.get("pv"), f.get("grid"), f.get("house"), f.get("ev") or 0.0
        if pv is None or grid is None or house is None or abs(ev) > 300:
            return  # a part missing, or the car charging (in the house's sensor or not - not known for sure)
        cands = self._bal_cands(roles)
        c = {e: v for es in cands.values() for e in es if (v := _watts(st.get(e))) is not None}
        self.bal.append({"pv": pv, "grid": grid, "batt": f.get("battery") or 0.0, "house": house, "c": c})
        if now - self.bal_at < BAL_EVERY:
            return
        self.bal_at = now
        signable = {r for r, pair in (("grid_power", self.ov.grid_pair()), ("battery_power", self.ov.battery_pair())) if pair is None}
        self.balance_state = res = judge(list(self.bal), cands, signable)
        fix = res.get("fix")
        if not fix:
            return
        role, key = fix["role"], f"balance:{fix['role']}"
        if self._ignored(key):
            return
        if fix["kind"] == "sign":
            name, old = ("grid_sign", self.ov.grid_sign()) if role == "grid_power" else ("battery_sign", self.ov.battery_sign())
            self._done(key, "balance_sign", old, -old, {name: -old})
        else:
            chosen = self.ov.settings.get("roles") or {}
            self._done(key, "balance", roles.get(role), fix["entity"], {"roles": {**chosen, role: fix["entity"]}})
        self.bal.clear()  # judged again on what the new reading shows
        self.balance_state = {"ok": None}

    def _alternative(self, role: str, bad: str, st: dict[str, Any], now: float) -> str | None:
        from datetime import datetime

        for c in (self.ov.candidates().get(role) or []):
            e = c.get("entity_id")
            if not e or e == bad or not c.get("guess"):
                continue
            name = str(((st.get(e) or {}).get("attributes") or {}).get("friendly_name") or "")
            if (PHASE_METER.search(e) or PHASE_METER.search(name)) and self._phases() == 3:
                continue  # one phase of three: the house would look a third of its size
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

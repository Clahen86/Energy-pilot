"""Stop selling solar when the price is negative: the inverter's export limit goes to 0 while selling would cost money,
and back to what it was afterwards. The house and the battery still use all the sun - only the grid gets none.

It follows the battery's mode: in shadow it only shows what it would do; in control it sets the chosen setting.
Off until the user turns it on and picks the setting (Settings -> Solar), because it changes the inverter.
"""

from __future__ import annotations

from datetime import datetime
import logging
import re
import time
from typing import Any

_LOGGER = logging.getLogger(__name__)
# Settings that limit what goes to the grid, by brand: a number in W or %, a mode to choose, or a switch.
PATTERNS = [
    r"^number\..*(export_limit|export_power_limit|feed_?in_limit|max_feed_?in|grid_export_limit|export_control_user_limit|export_power_rate|active_power_limit|zero_export|export_max)",
    r"^select\..*(export_limiter|active_power_control|export_rule|allow_export|limit_control_mode|export_limit_mode|zero_export)",
    r"^switch\..*(export_limit|export_power_limit|feed_?in|zero_export|grid_export)",
]
# By brand (the battery's inverter profile): the settings that stop the export, and the value. Growatt needs the
# limiter on AND the limit at 0 %.
PRESETS = {
    "growatt": [(r"^select\..*export_limiter$", "Enabled"), (r"^number\..*export_power_rate$", "0")],
    "growatt_tlxh": [(r"^select\..*export_limit(er)?(_enabled|_mode)?$", "Enabled"), (r"^number\..*export_(power_rate|limit_power_rate)$", "0")],
}
TEST_S = 120  # the test: how long it waits for the export to stop
RESET_S = 1800  # set again every 30 minutes while it lasts (an inverter may put its own value back)


def candidates(states: dict[str, Any]) -> list[dict[str, Any]]:
    """The settings in Home Assistant that look like an export limit - for the user to pick from."""
    out = []
    for e, st in states.items():
        if any(re.search(p, e) for p in PATTERNS) and (st.get("state") not in (None, "unavailable")):
            a = st.get("attributes") or {}
            out.append({"entity_id": e, "name": a.get("friendly_name") or e, "state": st.get("state"), "options": a.get("options"),
                        "unit": a.get("unit_of_measurement"), "min": a.get("min")})
    return sorted(out, key=lambda c: (not c["entity_id"].startswith("number."), c["name"]))


class Curtail:
    def __init__(self, ha: Any, ov: Any, controller: Any) -> None:
        self.ha, self.ov, self.ctl = ha, ov, controller
        self.last: dict[str, Any] = {}
        self.testing = False

    def suggest(self) -> dict[str, Any] | None:
        """What to use, from the brand: the known settings for the inverter - else the first export limit found (to 0)."""
        key = self.ctl.profile_key("battery") if self.ctl and hasattr(self.ctl, "profile_key") else None
        found = []
        for pat, val in PRESETS.get(key or "", []):
            e = next((x for x in sorted(self.ha.states) if re.search(pat, x)), None)
            if e:
                found.append((e, val))
        if found:
            return {"entity": found[0][0], "value": found[0][1], "extra": [list(x) for x in found[1:]], "from": key}
        num = next((c for c in candidates(self.ha.states) if c["entity_id"].startswith("number.")), None)
        return {"entity": num["entity_id"], "value": "0", "extra": [], "from": None} if num else None

    def targets(self) -> list[tuple[str, str]]:
        out = [(self.cfg["entity"], self.target())] if self.cfg.get("entity") and self.target() is not None else []
        return out + [(str(e), str(v)) for e, v in self.cfg.get("extra") or [] if e and e in self.ha.states]

    @property
    def cfg(self) -> dict[str, Any]:
        return self.ov.settings.get("curtail") or {}

    def sell_now(self) -> float | None:
        """What selling one kWh earns now: the feed-in price when it changes (a sensor or the tariff plan); otherwise
        the buying price itself when that is below 0 (then selling surely costs too)."""
        eng = self.ov.engine
        if not eng:
            return None
        now = datetime.now(eng.tz)
        sells = eng.sell_prices()
        if sells:
            return eng.sell_at(sells, now, 0.0)
        rows = [h for h in (self.ov.plan() or {}).get("hours") or [] if h.get("t") and h.get("price") is not None]
        past = [h for h in rows if datetime.fromisoformat(h["t"]) <= now]
        price = past[-1]["price"] if past else None
        return price if price is not None and price < 0 else 1.0

    def target(self) -> str | None:
        """The value that stops selling: 0 for a number, the chosen option for a mode, on/off for a switch."""
        e, c = self.cfg.get("entity") or "", self.cfg
        if e.startswith("number."):
            return str(c.get("value") if c.get("value") not in (None, "") else 0)
        if e.startswith(("select.", "switch.")):
            return str(c.get("value") or "") or None
        return None

    async def _set(self, e: str, v: str) -> bool:
        try:
            if e.startswith("number."):
                n = float(v)
                await self.ha.call_service(e.split(".")[0], "set_value", {"entity_id": e, "value": int(n) if n.is_integer() else n})
            elif e.startswith("select."):
                await self.ha.call_service("select", "select_option", {"entity_id": e, "option": v})
            elif e.startswith("switch."):
                await self.ha.call_service("switch", f"turn_{'on' if v == 'on' else 'off'}", {"entity_id": e})
            return True
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Could not set %s", e, exc_info=True)
            return False

    async def tick(self) -> None:
        c = self.cfg
        if c.get("on") and not c.get("entity") and (sg := self.suggest()):
            self.ov.save({"curtail": {**c, **sg}})  # turned on: chosen from the brand (it can be changed)
            c = self.cfg
        if self.testing or not c.get("on") or not self.targets():
            if not c.get("on"):
                self.last = {}
            return
        sell = self.sell_now()
        want = sell is not None and sell < float(c.get("below", 0) or 0)
        mode = self.ctl.mode("battery") if self.ctl else "shadow"
        saved = self.ov.settings.get("curtail_saved")
        self.last = {"want": want, "sell": sell, "mode": mode, "active": saved is not None, "t": time.time()}
        if mode != "control":
            return
        if want:
            if saved is None:
                saved = {e: st for e, _v in self.targets() if (st := (self.ha.states.get(e) or {}).get("state")) not in (None, "unknown", "unavailable")}
                self.ov.save({"curtail_saved": saved})  # the owner's own values, put back afterwards
            again = time.time() - float(c.get("_t") or 0) > RESET_S
            todo = [(e, v) for e, v in self.targets() if again or (self.ha.states.get(e) or {}).get("state") != v]
            ok = [await self._set(e, v) for e, v in todo]
            if todo and all(ok):
                _LOGGER.info("Selling stopped - the price is %s", sell)
                self.ov.save({"curtail": {**c, "_t": time.time()}})
        elif saved is not None:
            await self._put_back(saved)
            self.ov.save({"curtail_saved": None})

    async def _put_back(self, saved: dict[str, Any]) -> None:
        if "entity" in saved and "value" in saved and len(saved) == 2:
            saved = {saved["entity"]: saved["value"]}  # (an older version kept one)
        for e, v in saved.items():
            if v is not None:
                await self._set(e, str(v))
                _LOGGER.info("Selling allowed again - %s back to %s", e, v)

    async def test(self) -> dict[str, Any]:
        """The guide's test: stop selling for up to 2 minutes and see the export fall to (nearly) 0 - then put it back."""
        import asyncio

        if self.testing:
            return self.ov.settings.get("curtail_test") or {}
        res: dict[str, Any] = {"t": time.time(), "targets": self.targets()}
        grid = (self.ov.flow() or {}).get("grid")
        res["grid_before"] = grid
        if not self.targets():
            res["result"] = "no_setting"
        elif grid is None or grid > -150:
            res["result"] = "no_sun"  # nothing is sold right now - nothing to see
        else:
            self.testing = True
            saved = {e: (self.ha.states.get(e) or {}).get("state") for e, _v in self.targets()}
            res["saved"] = saved
            try:
                sent = [await self._set(e, v) for e, v in self.targets()]
                if not all(sent):
                    res["result"] = "rejected"
                else:
                    res["result"] = "failed"
                    for _ in range(TEST_S // 5):
                        await asyncio.sleep(5)
                        g = (self.ov.flow() or {}).get("grid")
                        res["grid_after"] = g
                        if g is not None and g > -60:
                            res["result"] = "ok"
                            break
                res["states_after"] = {e: (self.ha.states.get(e) or {}).get("state") for e, _v in self.targets()}
            finally:
                await self._put_back(saved)
                self.testing = False
        self.ov.save({"curtail_test": res})
        _LOGGER.info("Stop-selling test: %s", res["result"])
        return res

    def status(self) -> dict[str, Any]:
        return {**self.last, "candidates": candidates(self.ha.states), "suggest": self.suggest(), "testing": self.testing,
                "test": self.ov.settings.get("curtail_test")}

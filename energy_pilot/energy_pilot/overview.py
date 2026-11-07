"""What the panel shows: the energy flowing right now, today's plan, and only the parts the home has.

Each part (sun, battery, grid, car) is found from the states - a sensor chosen in the settings wins, otherwise a
known name, otherwise a guess from device class and words. A part that isn't found isn't shown anywhere.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

# Known names first (the user's own setup), then words to look for.
ROLES: dict[str, dict[str, Any]] = {
    "pv_power": {"known": ["sensor.growatt_sph_pv_power"], "class": "power", "words": ["pv_power", "solar_power", "sol_effekt", "pv"]},
    "house_power": {"known": ["sensor.husets_forbrug_uden_bil"], "class": "power", "words": ["house", "hus", "load", "forbrug", "consumption"]},
    "battery_power": {"known": ["sensor.growatt_sph_battery_power"], "class": "power", "words": ["battery_power", "batteri_effekt"]},
    "battery_soc": {"known": ["sensor.growatt_sph_battery_state_of_charge"], "class": "battery", "words": ["state_of_charge", "soc", "battery_level"]},
    "grid_power": {"known": ["sensor.growatt_sph_grid_power"], "class": "power", "words": ["grid_power", "net_effekt", "grid"]},
    "ev_power": {"known": ["sensor.keba_p30_charging_power"], "class": "power", "words": ["charging_power", "ladeeffekt", "wallbox", "charger"]},
    "ev_plug": {"known": ["binary_sensor.keba_p30_plug"], "class": "plug", "words": ["plug", "stik", "plugged"]},
    "ev_session": {"known": ["sensor.keba_p30_session_energy"], "class": "energy", "words": ["session_energy"]},
    "price": {"known": ["sensor.stromligning_current_price_vat"], "class": None, "words": ["price", "pris", "nordpool", "spot"]},
    "solar_today": {"known": ["sensor.solcast_pv_forecast_forecast_today"], "class": None, "words": ["forecast_today"]},
    "solar_tomorrow": {"known": ["sensor.solcast_pv_forecast_forecast_tomorrow"], "class": None, "words": ["forecast_tomorrow"]},
    "house_forecast": {"known": ["sensor.ml_forecast_appdaemon"], "class": None, "words": []},
    "battery_plan": {"known": ["sensor.appdaemon_comparison_controller"], "class": None, "words": []},
    "ev_manual": {"known": ["input_boolean.bil_lad_manuelt"], "class": None, "words": []},
    "ev_ready": {"known": ["input_datetime.bil_klar_tid"], "class": None, "words": []},
    "ev_cap": {"known": ["input_number.bil_lad_loft_kwh"], "class": None, "words": []},
}

DECISIONS = {
    "da": {
        "FREE_DISCHARGE": ("Batteriet forsyner huset", "discharge"), "DISCHARGE": ("Batteriet forsyner huset", "discharge"),
        "FREE_CHARGE": ("Batteriet lader", "charge"), "CHARGE": ("Batteriet lader", "charge"),
        "GRID_CHARGE": ("Lader batteriet med billig strøm", "grid"), "FREE_GRID_CHARGE": ("Lader batteriet med billig strøm", "grid"),
        "FREE_HOLD": ("Gemmer strømmen til senere", "hold"), "HOLD": ("Gemmer strømmen til senere", "hold"),
        "NOOP": ("Alt kører som planlagt", "hold"),
    },
    "en": {
        "FREE_DISCHARGE": ("The battery powers the house", "discharge"), "DISCHARGE": ("The battery powers the house", "discharge"),
        "FREE_CHARGE": ("The battery is charging", "charge"), "CHARGE": ("The battery is charging", "charge"),
        "GRID_CHARGE": ("Charging the battery with cheap power", "grid"), "FREE_GRID_CHARGE": ("Charging the battery with cheap power", "grid"),
        "FREE_HOLD": ("Saving the power for later", "hold"), "HOLD": ("Saving the power for later", "hold"),
        "NOOP": ("Everything runs as planned", "hold"),
    },
}


def _num(state: dict | None) -> float | None:
    if not state:
        return None
    try:
        return float(state.get("state"))
    except (TypeError, ValueError):
        return None


def _watts(state: dict | None) -> float | None:
    v = _num(state)
    if v is None:
        return None
    unit = str((state.get("attributes") or {}).get("unit_of_measurement") or "W")
    return v * 1000 if unit.lower() == "kw" else v


class Overview:
    def __init__(self, ha: Any, data_dir: Path) -> None:
        self.ha = ha
        self.file = data_dir / "energy_pilot_settings.json"
        self.settings: dict[str, Any] = self._load()
        self.detected: dict[str, dict[str, str]] = {}
        self.engine: Any = None
        self.controller: Any = None
        self.price_info: dict[str, Any] = {}

    async def async_detect(self) -> None:
        from .detect import detect

        try:
            self.detected = await detect(self.ha)
        except Exception:  # noqa: BLE001 - keep what was found before
            import logging

            logging.getLogger(__name__).warning("Finding the parts failed", exc_info=True)

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self.file.read_text())
        except (OSError, ValueError):
            return {"roles": {}, "battery_kwh": None, "import_limit_kw": 10}

    def save(self, changes: dict[str, Any]) -> None:
        for key, value in changes.items():
            if key == "roles":
                self.settings.setdefault("roles", {}).update({k: v for k, v in value.items() if k in ROLES})
            elif key in ("battery_kwh", "import_limit_kw", "language", "setup_done", "style", "price_area", "tariff", "markup", "price_source", "tou", "vat", "battery_min_soc", "grid_charge",
                         "sell", "sell_price", "battery_charge_kw", "battery_discharge_kw", "ev_mode", "charger_kw", "ev_need_kwh",
                         "quiet_from", "quiet_to", "quiet_battery", "quiet_car",
                         "quiet_battery_from", "quiet_battery_to", "quiet_car_from", "quiet_car_to",
                         "control", "inverter_profile", "custom_profile", "battery_takeover", "ev_now", "charger_phases", "ev_ready"):
                self.settings[key] = value
        self.file.write_text(json.dumps(self.settings, indent=2))

    # ---------- finding the parts ----------

    def role(self, name: str) -> str | None:
        if name == "price" and self.settings.get("price_source") in ("tou", "spot"):
            return None  # the user picked Energy Pilot's own prices
        chosen = (self.settings.get("roles") or {}).get(name)
        states = self.ha.states
        if chosen == "":
            return None  # switched off by the user
        if chosen and chosen in states:
            return chosen
        spec = ROLES[name]
        for e in spec["known"]:
            if e in states and states[e].get("state") not in ("unavailable", "unknown", None):
                return e
        found = (self.detected.get(name) or {}).get("entity_id")
        return found if found in states else None

    def source(self, name: str) -> str | None:
        """Where a part was found: "chosen", "known", "energy", "integration:<platform>", "name" or "computed"."""
        chosen = (self.settings.get("roles") or {}).get(name)
        if chosen:
            return "chosen"
        e = self.role(name)
        if e is None:
            if name == "house_power" and self.role("grid_power") and self.role("pv_power"):
                return "computed"
            eng = self.engine
            if eng and ((name == "price" and eng.own_prices) or (name in ("solar_today", "solar_tomorrow") and eng.own_solar)
                        or (name == "house_forecast" and eng.house_model.model is not None)):
                return "own"
            return None
        if e in ROLES[name]["known"]:
            return "known"
        return (self.detected.get(name) or {}).get("source")

    def roles(self) -> dict[str, str | None]:
        return {name: self.role(name) for name in ROLES}

    def candidates(self) -> dict[str, list[dict[str, str]]]:
        """For the settings: entities that could fill each part."""
        out: dict[str, list[dict[str, str]]] = {}
        for name, spec in ROLES.items():
            rows = []
            for e, s in self.ha.states.items():
                a = s.get("attributes") or {}
                cls = spec["class"]
                domain = e.split(".")[0]
                if cls == "power" and a.get("device_class") != "power":
                    continue
                if cls == "battery" and a.get("device_class") != "battery":
                    continue
                if cls == "plug" and (domain != "binary_sensor" or a.get("device_class") not in ("plug", "power", None)):
                    continue
                if cls == "energy" and a.get("device_class") != "energy":
                    continue
                if cls is None and e not in spec["known"] and not any(w in e for w in spec["words"]):
                    continue
                if spec["words"] and cls is not None and not any(w in e for w in spec["words"]) and e not in spec["known"]:
                    continue
                rows.append({"entity_id": e, "name": a.get("friendly_name") or e})
            found = self.role(name)
            if found and not any(r["entity_id"] == found for r in rows):
                rows.append({"entity_id": found, "name": (self.ha.states[found].get("attributes") or {}).get("friendly_name") or found})
            out[name] = sorted(rows, key=lambda r: r["name"].lower())[:40]
        return out

    # ---------- now ----------

    def flow(self) -> dict[str, Any]:
        r, st = self.roles(), self.ha.states
        pv = _watts(st.get(r["pv_power"])) if r["pv_power"] else None
        house = _watts(st.get(r["house_power"])) if r["house_power"] else None
        batt = _watts(st.get(r["battery_power"])) if r["battery_power"] else None
        soc = _num(st.get(r["battery_soc"])) if r["battery_soc"] else None
        grid = _watts(st.get(r["grid_power"])) if r["grid_power"] else None
        ev = _watts(st.get(r["ev_power"])) if r["ev_power"] else None
        plug = (st.get(r["ev_plug"]) or {}).get("state") == "on" if r["ev_plug"] else None
        # Positive battery = charging (Growatt reports discharge as negative). Grid: positive = buying.
        if grid is None and None not in (pv, house):
            grid = (house or 0) + (ev or 0) + (batt or 0) - (pv or 0)
        if house is None and None not in (pv, grid):
            house = max(0.0, (pv or 0) + (grid or 0) - (batt or 0) - (ev or 0))  # what's left is the house
        return {
            "pv": pv, "house": house, "battery": batt, "soc": soc, "grid": grid, "ev": ev, "plug": plug,
            "has": {"pv": pv is not None, "battery": soc is not None or batt is not None, "grid": grid is not None,
                    "ev": r["ev_power"] is not None or r["ev_plug"] is not None},
        }

    def engine_decision(self, lang: str) -> dict[str, Any] | None:
        b = ((self.engine.result if self.engine else None) or {}).get("battery")
        if not b:
            return None
        key = {"discharge": "FREE_DISCHARGE", "charge": "FREE_CHARGE", "grid": "GRID_CHARGE", "hold": "FREE_HOLD"}[b["now"]]
        text, kind = DECISIONS.get(lang, DECISIONS["en"])[key]
        return {"key": key, "text": text, "kind": kind, "reason": None, "target": b["target"], "plan": [], "engine": True,
                "saving": b["saving"]}

    def decision(self, lang: str) -> dict[str, Any] | None:
        e = self.role("battery_plan")
        s = self.ha.states.get(e) if e else None
        if not s:
            return self.engine_decision(lang)
        a = s.get("attributes") or {}
        key = str(s.get("state"))
        text, kind = DECISIONS.get(lang, DECISIONS["en"]).get(key, (key.replace("_", " ").capitalize(), "hold"))
        return {"key": key, "text": text, "kind": kind, "reason": a.get("appdaemon_reason"),
                "target": a.get("ad_soc_target"), "plan": a.get("battery_charge_plan") or []}

    # ---------- today's plan ----------

    def plan(self) -> dict[str, Any]:
        """Hour by hour for today and tomorrow (as far as prices reach): price, sun, house, battery charging."""
        tz = ZoneInfo(self.ha.config.get("time_zone") or "UTC")
        now = datetime.now(tz)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        hours: dict[str, dict[str, Any]] = {}

        def slot(dt: datetime) -> dict[str, Any] | None:
            dt = dt.astimezone(tz)
            if dt < start or dt >= start + timedelta(days=2):
                return None
            key = dt.strftime("%Y-%m-%dT%H")
            return hours.setdefault(key, {"t": dt.replace(minute=0, second=0, microsecond=0).isoformat()})

        from .pricefeed import collect

        prices, self.price_info = collect(self.ha.states, self.role("price"),
                                          (self.engine.own_prices if self.engine else []) or [], tz)
        if prices:
            buckets: dict[str, list[float]] = {}
            for dt, value in prices.items():
                if (h := slot(dt)) is not None:
                    buckets.setdefault(h["t"], []).append(value)
            for key, h in hours.items():
                if h["t"] in buckets:
                    h["price"] = round(sum(buckets[h["t"]]) / len(buckets[h["t"]]), 3)
        for role in ("solar_today", "solar_tomorrow"):
            if (e := self.role(role)) and (s := self.ha.states.get(e)):
                for p in (s.get("attributes") or {}).get("detailedHourly") or []:
                    try:
                        dt = datetime.fromisoformat(str(p.get("period_start")))
                        kwh = float(p.get("pv_estimate"))
                    except (TypeError, ValueError):
                        continue
                    if (h := slot(dt)) is not None:
                        h["sun"] = round(kwh, 2)
        if not self.role("solar_today") and self.engine and self.engine.own_solar:
            for when, kwh in self.engine.own_solar.items():
                if (h := slot(when)) is not None:
                    h["sun"] = kwh
        if (e := self.role("house_forecast")) and (s := self.ha.states.get(e)):
            hourly = (s.get("attributes") or {}).get("hourly_kwh") or []
            if isinstance(hourly, list):
                for i, kwh in enumerate(hourly[:24]):
                    if isinstance(kwh, (int, float)) and (h := slot(start + timedelta(hours=i))) is not None:
                        h["house"] = round(kwh, 2)
            elif isinstance(hourly, dict):
                for k, kwh in hourly.items():
                    try:
                        if (h := slot(start + timedelta(hours=int(k)))) is not None:
                            h["house"] = round(float(kwh), 2)
                    except (TypeError, ValueError):
                        continue
        if (d := self.decision("da")):
            for p in d["plan"]:
                try:
                    hour = int(p.get("hour"))
                except (TypeError, ValueError):
                    continue
                dt = start + timedelta(hours=hour)
                if dt.hour < now.hour - 1:
                    dt += timedelta(days=1)
                if (h := slot(dt)) is not None:
                    h["charge"] = p.get("charge_pct")
        res = (self.engine.result if self.engine else None) or {}
        for st in (res.get("battery") or {}).get("steps", []):
            if (h := slot(datetime.fromisoformat(st["t"]))) is not None:
                h["soc"] = st["soc"]
                if not self.role("battery_plan") and st["action"] in ("charge_grid", "charge_sun"):
                    h["charge"] = True
        for t in (res.get("car") or {}).get("hours", []):
            if (h := slot(datetime.fromisoformat(t))) is not None:
                h["car"] = True
        if not self.role("house_forecast"):
            for row in res.get("house", []):
                if (h := slot(datetime.fromisoformat(row["t"]))) is not None:
                    h.setdefault("house", row["kwh"])
        rows = sorted(hours.values(), key=lambda h: h["t"])
        prices = [h["price"] for h in rows if "price" in h]
        cheapest = sorted((h for h in rows if "price" in h and h["t"] >= now.replace(minute=0, second=0, microsecond=0).isoformat()),
                          key=lambda h: h["price"])[:3]
        return {"now": now.isoformat(), "hours": rows,
                "price_min": min(prices) if prices else None, "price_max": max(prices) if prices else None,
                "cheapest": sorted(h["t"] for h in cheapest)}

    def ev(self) -> dict[str, Any] | None:
        r, st = self.roles(), self.ha.states
        if not (r["ev_power"] or r["ev_plug"]):
            return None

        def val(role: str) -> Any:
            return (st.get(r[role]) or {}).get("state") if r[role] else None

        # Without helpers of its own, the car's buttons are Energy Pilot's (its settings).
        return {"manual": val("ev_manual") == "on" if r["ev_manual"] else bool(self.settings.get("ev_now")),
                "ready": val("ev_ready") if r["ev_ready"] else self.settings.get("ev_ready"),
                "cap": _num(st.get(r["ev_cap"])) if r["ev_cap"] else self.settings.get("ev_need_kwh"),
                "cap_max": ((st.get(r["ev_cap"]) or {}).get("attributes") or {}).get("max") if r["ev_cap"] else None,
                "session_kwh": _num(st.get(r["ev_session"])) if r["ev_session"] else None,
                "entities": {k: r[k] for k in ("ev_manual", "ev_ready", "ev_cap")}}

    def snapshot(self, lang: str = "da") -> dict[str, Any]:
        price_e = self.role("price")
        price = self.ha.states.get(price_e) if price_e else None
        if price is None and self.engine and self.engine.own_prices:
            now = datetime.now(ZoneInfo(self.ha.config.get("time_zone") or "UTC"))
            cur = [p for p in self.engine.own_prices if datetime.fromisoformat(p["start"]) <= now < datetime.fromisoformat(p["end"])]
            if cur:
                price = {"state": cur[0]["price"], "attributes": {"unit_of_measurement": "kr/kWh"}}
        solar = {k: _num(self.ha.states.get(self.role(k))) if self.role(k) else None for k in ("solar_today", "solar_tomorrow")}
        house_e = self.role("house_forecast")
        return {
            "flow": self.flow(), "decision": self.decision(lang), "plan": self.plan(), "ev": self.ev(),
            "price": {"now": _num(price), "unit": ((price or {}).get("attributes") or {}).get("unit_of_measurement")},
            "solar": solar, "house_today": _num(self.ha.states.get(house_e)) if house_e else None,
            "settings": self.settings,
        }

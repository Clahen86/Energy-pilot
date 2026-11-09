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
    "price": {"known": ["sensor.stromligning_current_price_vat"], "class": None,
              "words": ["price", "pris", "nordpool", "spot", "current_rate", "day_rates", "tariff", "tarif_actuel"]},
    "solar_today": {"known": ["sensor.solcast_pv_forecast_forecast_today"], "class": None, "words": ["forecast_today"]},
    "solar_tomorrow": {"known": ["sensor.solcast_pv_forecast_forecast_tomorrow"], "class": None, "words": ["forecast_tomorrow"]},
    "house_forecast": {"known": ["sensor.ml_forecast_appdaemon"], "class": None, "words": []},
    "battery_cost": {"known": ["sensor.batteri_gennemsnitlig_kostpris_dkk_kwh"], "class": None, "words": ["kostpris", "battery_cost", "stored_cost", "average_cost"]},
    "battery_plan": {"known": ["sensor.appdaemon_comparison_controller"], "class": None, "words": []},
    # A feed-in price that changes (Amber, Tibber export …) - instead of the fixed sell price. Only when chosen.
    # Off-grid: the generator's on/off control and (optionally) whether it is running. Only when chosen.
    "generator_switch": {"known": [], "class": None, "words": ["generator", "genset"]},
    "generator_running": {"known": [], "class": None, "words": ["generator", "genset"]},
    "sell_price": {"known": [], "class": None, "words": ["feed_in", "feedin", "export_price", "export_current", "export", "sell_price", "salgspris"]},
    "ev_manual": {"known": ["input_boolean.bil_lad_manuelt"], "class": None, "words": []},
    "ev_ready": {"known": ["input_datetime.bil_klar_tid"], "class": None, "words": []},
    "ev_cap": {"known": ["input_number.bil_lad_loft_kwh"], "class": None, "words": []},
}

DECISIONS = {
    "da": {
        "FREE_DISCHARGE": ("Batteriet forsyner huset", "discharge"), "DISCHARGE": ("Batteriet forsyner huset", "discharge"),
        "FREE_CHARGE": ("Batteriet lader", "charge"), "CHARGE": ("Batteriet lader", "charge"),
        "GRID_CHARGE": ("Lader batteriet med billig strøm", "grid"), "FREE_GRID_CHARGE": ("Lader batteriet med billig strøm", "grid"),
        "FREE_HOLD": ("Gemmer strømmen til senere", "hold"), "FREE_EXPORT": ("Sælger strøm fra batteriet", "export"), "HOLD": ("Gemmer strømmen til senere", "hold"),
        "NOOP": ("Alt kører som planlagt", "hold"),
    },
    "en": {
        "FREE_DISCHARGE": ("The battery powers the house", "discharge"), "DISCHARGE": ("The battery powers the house", "discharge"),
        "FREE_CHARGE": ("The battery is charging", "charge"), "CHARGE": ("The battery is charging", "charge"),
        "GRID_CHARGE": ("Charging the battery with cheap power", "grid"), "FREE_GRID_CHARGE": ("Charging the battery with cheap power", "grid"),
        "FREE_HOLD": ("Saving the power for later", "hold"), "FREE_EXPORT": ("Selling power from the battery", "export"), "HOLD": ("Saving the power for later", "hold"),
        "NOOP": ("Everything runs as planned", "hold"),
    },
    "de": {
        "FREE_DISCHARGE": ("Die Batterie versorgt das Haus", "discharge"), "DISCHARGE": ("Die Batterie versorgt das Haus", "discharge"),
        "FREE_CHARGE": ("Die Batterie lädt", "charge"), "CHARGE": ("Die Batterie lädt", "charge"),
        "GRID_CHARGE": ("Lädt die Batterie mit günstigem Strom", "grid"), "FREE_GRID_CHARGE": ("Lädt die Batterie mit günstigem Strom", "grid"),
        "FREE_HOLD": ("Hebt den Strom für später auf", "hold"), "FREE_EXPORT": ("Verkauft Strom aus der Batterie", "export"), "HOLD": ("Hebt den Strom für später auf", "hold"),
        "NOOP": ("Alles läuft nach Plan", "hold"),
    },
    "fr": {
        "FREE_DISCHARGE": ("La batterie alimente la maison", "discharge"), "DISCHARGE": ("La batterie alimente la maison", "discharge"),
        "FREE_CHARGE": ("La batterie charge", "charge"), "CHARGE": ("La batterie charge", "charge"),
        "GRID_CHARGE": ("Charge la batterie avec de l'électricité bon marché", "grid"), "FREE_GRID_CHARGE": ("Charge la batterie avec de l'électricité bon marché", "grid"),
        "FREE_HOLD": ("Garde l'énergie pour plus tard", "hold"), "FREE_EXPORT": ("Vend l'énergie de la batterie", "export"), "HOLD": ("Garde l'énergie pour plus tard", "hold"),
        "NOOP": ("Tout se déroule comme prévu", "hold"),
    },
    "nl": {
        "FREE_DISCHARGE": ("De batterij voedt het huis", "discharge"), "DISCHARGE": ("De batterij voedt het huis", "discharge"),
        "FREE_CHARGE": ("De batterij laadt", "charge"), "CHARGE": ("De batterij laadt", "charge"),
        "GRID_CHARGE": ("Laadt de batterij met goedkope stroom", "grid"), "FREE_GRID_CHARGE": ("Laadt de batterij met goedkope stroom", "grid"),
        "FREE_HOLD": ("Bewaart de stroom voor later", "hold"), "FREE_EXPORT": ("Verkoopt stroom uit de batterij", "export"), "HOLD": ("Bewaart de stroom voor later", "hold"),
        "NOOP": ("Alles loopt volgens plan", "hold"),
    },
    "sv": {
        "FREE_DISCHARGE": ("Batteriet försörjer huset", "discharge"), "DISCHARGE": ("Batteriet försörjer huset", "discharge"),
        "FREE_CHARGE": ("Batteriet laddar", "charge"), "CHARGE": ("Batteriet laddar", "charge"),
        "GRID_CHARGE": ("Laddar batteriet med billig ström", "grid"), "FREE_GRID_CHARGE": ("Laddar batteriet med billig ström", "grid"),
        "FREE_HOLD": ("Sparar strömmen till senare", "hold"), "FREE_EXPORT": ("Säljer ström från batteriet", "export"), "HOLD": ("Sparar strömmen till senare", "hold"),
        "NOOP": ("Allt går som planerat", "hold"),
    },
    "nb": {
        "FREE_DISCHARGE": ("Batteriet forsyner huset", "discharge"), "DISCHARGE": ("Batteriet forsyner huset", "discharge"),
        "FREE_CHARGE": ("Batteriet lader", "charge"), "CHARGE": ("Batteriet lader", "charge"),
        "GRID_CHARGE": ("Lader batteriet med billig strøm", "grid"), "FREE_GRID_CHARGE": ("Lader batteriet med billig strøm", "grid"),
        "FREE_HOLD": ("Sparer strømmen til senere", "hold"), "FREE_EXPORT": ("Selger strøm fra batteriet", "export"), "HOLD": ("Sparer strømmen til senere", "hold"),
        "NOOP": ("Alt går som planlagt", "hold"),
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
                         "sell", "sell_price", "solar_value", "ev_in_house", "battery_sign", "ev_follow_sun", "ev_fuse_guard",
                         "battery_export", "battery_wear", "export_limit_kw", "agile_region", "restore_values",
                         "offgrid", "reserve_soc", "emergency_soc", "gen_stop_soc", "gen_charge_kw", "gen_min_run_h",
                         "quiet_gen_from", "quiet_gen_to", "battery_charge_kw", "battery_discharge_kw", "ev_mode", "charger_kw", "ev_need_kwh",
                         "quiet_from", "quiet_to", "quiet_battery", "quiet_car",
                         "quiet_battery_from", "quiet_battery_to", "quiet_car_from", "quiet_car_to",
                         "control", "inverter_profile", "custom_profile", "battery_takeover", "ev_now", "charger_phases", "ev_ready",
                         "batteries", "battery_dismissed", "chargers", "charger_dismissed"):
                self.settings[key] = value
        self.file.write_text(json.dumps(self.settings, indent=2))

    # ---------- finding the parts ----------

    def _price_now_from_rates(self) -> float | None:
        """An event entity (Octopus' current day rates) has no number as its state: the slot now from its rates."""
        from .pricefeed import now_price

        return now_price(self.ha.states, self.role("price"), ZoneInfo(self.ha.config.get("time_zone") or "UTC"))

    def battery_sign(self) -> int:
        """+1: positive battery power is charging (Growatt). -1: positive is discharging (Fox ESS). Chosen, or found."""
        chosen = self.settings.get("battery_sign")
        if chosen in (1, -1):
            return chosen
        return (self.engine.sign_found() if self.engine else None) or 1

    def role_all(self, name: str) -> list[str]:
        """Every entity for a part - solar can be several arrays (and forecasts), added up."""
        chosen = (self.settings.get("roles") or {}).get(name)
        if isinstance(chosen, list):
            return [e for e in chosen if e in self.ha.states]
        one = self.role(name)
        return [one] if one else []

    def role(self, name: str) -> str | None:
        if name == "price" and self.settings.get("price_source") in ("tou", "spot"):
            return None  # the user picked Energy Pilot's own prices
        chosen = (self.settings.get("roles") or {}).get(name)
        states = self.ha.states
        if name in ("sell_price", "generator_switch", "generator_running") and not chosen:
            return None  # a changing feed-in price only when the user picks one
        if isinstance(chosen, list):  # several (solar arrays): the first stands for them where only one fits
            chosen = next((e for e in chosen if e in states), None)
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
                unit = str(a.get("unit_of_measurement") or "").lower()
                dc = a.get("device_class")
                # The right kind by device class, or by unit when a template or integration doesn't set one
                # (Victron, templates that add two solar arrays together …).
                if cls == "power" and not (dc == "power" or (domain == "sensor" and not dc and unit in ("w", "kw"))):
                    continue
                if cls == "battery" and not (dc == "battery" or (domain == "sensor" and not dc and unit == "%")):
                    continue
                # A binary plug sensor, or a charger's status list (VEVOR, OCPP …) that says when the car is in.
                if cls == "plug" and not ((domain == "binary_sensor" and dc in ("plug", "power", None))
                                          or (domain == "sensor" and dc == "enum")):
                    continue
                if cls == "energy" and not (dc == "energy" or (domain == "sensor" and not dc and unit in ("kwh", "wh"))):
                    continue
                guess = e in spec["known"] or any(w in e for w in spec["words"])
                if name in ("solar_today", "solar_tomorrow") and not guess and domain == "sensor" and unit in ("kwh", "wh"):
                    # Forecast.Solar (energy_production_today), Open-Meteo and others are named otherwise: every
                    # kWh sensor is listed, the forecast-looking ones first - never picked by itself
                    day = name.split("_")[1]
                    if not (day in e and any(w in e for w in ("forecast", "prognose", "production", "prediction"))):
                        rows.append({"entity_id": e, "name": a.get("friendly_name") or e, "guess": False})
                        continue
                    guess = True
                if cls is None and not guess:
                    continue
                rows.append({"entity_id": e, "name": a.get("friendly_name") or e, "guess": guess})
            found = self.role(name)
            if found and not any(r["entity_id"] == found for r in rows):
                rows.append({"entity_id": found, "name": (self.ha.states[found].get("attributes") or {}).get("friendly_name") or found, "guess": True})
            for e in self.role_all(name):
                if not any(r["entity_id"] == e for r in rows):
                    rows.append({"entity_id": e, "name": (self.ha.states[e].get("attributes") or {}).get("friendly_name") or e, "guess": True})
            # Best guesses first, then the rest by name.
            out[name] = sorted(rows, key=lambda r: (not r.get("guess"), str(r["name"]).lower()))[:150]
        return out

    def all_sensors(self) -> list[dict[str, str]]:
        """Every sensor, for the search field - for whoever can't find theirs in the list."""
        return sorted(({"entity_id": e, "name": (s.get("attributes") or {}).get("friendly_name") or e}
                       for e, s in self.ha.states.items() if e.split(".")[0] in ("sensor", "binary_sensor")),
                      key=lambda r: r["name"].lower())

    # ---------- now ----------

    def main_battery_kwh(self) -> float:
        """Battery 1's size when there are more: what's set, else a capacity sensor, else 10 kWh."""
        guess = self.engine._guess_capacity() if self.engine else None
        return float(self.settings.get("battery_kwh") or guess or 10)

    def flow(self) -> dict[str, Any]:
        r, st = self.roles(), self.ha.states
        arrays = [w for e in self.role_all("pv_power") if (w := _watts(st.get(e))) is not None]
        pv = sum(arrays) if arrays else None  # several arrays are added up
        house = _watts(st.get(r["house_power"])) if r["house_power"] else None
        batt = _watts(st.get(r["battery_power"])) if r["battery_power"] else None
        if batt is not None:
            batt *= self.battery_sign()  # some integrations (Fox ESS Modbus …) count discharging as positive
        soc = _num(st.get(r["battery_soc"])) if r["battery_soc"] else None
        packs = None
        from . import batteries

        if more := batteries.extras(self.settings):
            # More than one battery: the plan sees one - the level weighted by size, the powers added up.
            main = {"name": "", "soc": soc, "power": batt, "kwh": self.main_battery_kwh()}
            others = [batteries.read(st, b) for b in more]
            soc, batt = batteries.combine(main, others)
            packs = [main] + others
        grid = _watts(st.get(r["grid_power"])) if r["grid_power"] else None
        ev = _watts(st.get(r["ev_power"])) if r["ev_power"] else None
        from . import chargers

        plug = chargers.is_plugged((st.get(r["ev_plug"]) or {}).get("state")) if r["ev_plug"] else None

        cars = [chargers.read(st, c) for c in chargers.extras(self.settings)] or None
        if cars and any(c["power"] is not None for c in cars):
            ev = (ev or 0.0) + sum(c["power"] or 0.0 for c in cars)  # all the chargers: shown and taken out of the house together
        # Positive battery = charging (Growatt reports discharge as negative). Grid: positive = buying.
        if house is not None and ev and self.engine and self.engine.ev_in_house():
            house = max(0.0, house - ev)  # the car is in the house's sensor: it is shown (and planned) on its own
        if grid is None and None not in (pv, house):
            grid = (house or 0) + (ev or 0) + (batt or 0) - (pv or 0)
        if house is None and None not in (pv, grid):
            house = max(0.0, (pv or 0) + (grid or 0) - (batt or 0) - (ev or 0))  # what's left is the house
        return {
            "pv": pv, "house": house, "battery": batt, "soc": soc, "grid": grid, "ev": ev, "plug": plug, "batteries": packs, "cars": cars,
            "has": {"pv": pv is not None, "battery": soc is not None or batt is not None, "grid": grid is not None,
                    "ev": r["ev_power"] is not None or r["ev_plug"] is not None},
        }

    def engine_decision(self, lang: str) -> dict[str, Any] | None:
        b = ((self.engine.result if self.engine else None) or {}).get("battery")
        if not b:
            return None
        key = {"discharge": "FREE_DISCHARGE", "charge": "FREE_CHARGE", "grid": "GRID_CHARGE", "hold": "FREE_HOLD", "export": "FREE_EXPORT"}[b["now"]]
        text, kind = DECISIONS.get(lang, DECISIONS["en"])[key]
        return {"key": key, "text": text, "kind": kind, "reason": None, "target": b["target"], "plan": [], "engine": True,
                "saving": b["saving"]}

    def decision(self, lang: str) -> dict[str, Any] | None:
        """Energy Pilot's own decision - the same plan as the curve below it. Another system (AppDaemon) that
        plans the battery is shown beside it, so the two can be compared."""
        own, other = self.engine_decision(lang), self.other_decision(lang)
        if not own:
            return other
        if other:
            own = {**own, "other": {"text": other["text"], "kind": other["kind"]}}
        return own

    def other_decision(self, lang: str) -> dict[str, Any] | None:
        """What another system planning the battery (AppDaemon) decided - None when there is none."""
        e = self.role("battery_plan")
        s = self.ha.states.get(e) if e else None
        if not s:
            return None
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
                                          (self.engine.own_prices if self.engine else []) or [], tz,
                                          (self.engine.service_prices if self.engine else []) or [])
        self.fine_prices = prices  # quarter/half-hour prices as they come - the engine plans in those slots
        if prices:
            buckets: dict[str, list[float]] = {}
            for dt, value in prices.items():
                if (h := slot(dt)) is not None:
                    buckets.setdefault(h["t"], []).append(value)
            for key, h in hours.items():
                if h["t"] in buckets:
                    h["price"] = round(sum(buckets[h["t"]]) / len(buckets[h["t"]]), 3)
        # Tomorrow's prices before they're out (around 13:00): estimated - replaced by the real ones when they come.
        if self.engine and prices:
            last = max(prices)
            end = start.replace(hour=0) + timedelta(days=2)  # to the end of tomorrow
            gaps = [t for t in (start + timedelta(hours=i) for i in range(48))
                    if last < t < end and "price" not in hours.get(t.strftime("%Y-%m-%dT%H"), {})]
            if gaps:
                eng = self.engine
                est = eng.price_model.estimate(gaps, eng.weather if eng.weather and eng.weather.hours else None, eng.mixer.share("price"))
                # Octopus Agile: Agile Predict's forecast for the whole market wins over the own estimate.
                agile = getattr(eng, "agile_forecast", None) or {}
                if agile:
                    for t in gaps:
                        vals = [v for when, v in agile.items() if t <= when < t + timedelta(hours=1)]
                        if vals:
                            est[t] = sum(vals) / len(vals)
                    self.price_info["forecast"] = "Agile Predict"
                for when, v in est.items():
                    if (h := slot(when)) is not None:
                        h["price"], h["est"] = round(v, 3), True
                self.price_info["estimated"] = len(est)
        for role in ("solar_today", "solar_tomorrow"):
            for e in self.role_all(role):
                if not (s := self.ha.states.get(e)):
                    continue
                for p in (s.get("attributes") or {}).get("detailedHourly") or []:
                    try:
                        dt = datetime.fromisoformat(str(p.get("period_start")))
                        kwh = float(p.get("pv_estimate"))
                    except (TypeError, ValueError):
                        continue
                    if (h := slot(dt)) is not None:
                        h["sun"] = round(h.get("sun", 0.0) + kwh, 2)  # several forecasts (arrays) add up
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
        # The plan shows Energy Pilot's own charging; another system's plan (AppDaemon) is only compared.
        res = (self.engine.result if self.engine else None) or {}
        for st in (res.get("battery") or {}).get("steps", []):
            if (h := slot(datetime.fromisoformat(st["t"]))) is not None:
                h["soc"] = st["soc"]
                if st["action"] in ("charge_grid", "charge_sun"):
                    h["charge"] = True
                elif st["action"] == "export":
                    h["export"] = True  # sells from the battery
        for t in (res.get("car") or {}).get("hours", []):
            if (h := slot(datetime.fromisoformat(t))) is not None:
                h["car"] = True
        # The engine's own forecast covers every planned hour: it fills what another forecast doesn't reach
        # (an AppDaemon forecast that only covers today).
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
        solar = {k: (sum(v for e in self.role_all(k) if (v := _num(self.ha.states.get(e))) is not None) if self.role_all(k) else None)
                 for k in ("solar_today", "solar_tomorrow")}
        house_e = self.role("house_forecast")
        return {
            "flow": self.flow(), "decision": self.decision(lang), "plan": self.plan(), "ev": self.ev(),
            "price": {"now": _num(price) if _num(price) is not None else self._price_now_from_rates(),
                      "unit": ((price or {}).get("attributes") or {}).get("unit_of_measurement")},
            # Home today: the engine's own (what the plan uses); another system's forecast is shown beside it.
            "solar": solar,
            "house_today": (self.engine.house_today() if self.engine else None)
            or (_num(self.ha.states.get(house_e)) if house_e else None),
            "house_other": _num(self.ha.states.get(house_e)) if house_e and self.engine and self.engine.house_today() else None,
            "house_other_appdaemon": bool(house_e and "appdaemon" in house_e),
            "settings": self.settings,
        }

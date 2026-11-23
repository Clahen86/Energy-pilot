"""What the panel shows: the energy flowing right now, today's plan, and only the parts the home has.

Each part (sun, battery, grid, car) is found from the states - a sensor chosen in the settings wins, otherwise a
known name, otherwise a guess from device class and words. A part that isn't found isn't shown anywhere.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import re
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

# Known names first (the user's own setup), then words to look for.
GRID_SELL_PLUS = {"goodwe"}  # integrations whose grid power is plus when selling
# Where a price can live: a sensor, a helper, Octopus' rate events - never an update, a button or a switch.
PRICE_DOMAINS = ("sensor", "input_number", "number", "event")
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
    # The car's own battery level (%): from the car's integration only - see detect.car_socs.
    "ev_soc": {"known": [], "class": "battery", "words": []},
    "ev_manual": {"known": ["input_boolean.bil_lad_manuelt"], "class": None, "words": []},
    "ev_ready": {"known": ["input_datetime.bil_klar_tid"], "class": None, "words": []},
    "ev_cap": {"known": ["input_number.bil_lad_loft_kwh"], "class": None, "words": []},
}

NOTES = {  # a short line under "Right now" when something automatic changes the plan
    "da": {"away": "Ingen hjemme – planen regner med lavt forbrug, til nogen kommer hjem", "cold": "Batteriet er koldt og lader langsommere – planen tager højde for det", "power_down": "Octopus-session meldt til – batteriet gemmer strøm til den"},
    "en": {"away": "Nobody home – the plan counts on low use until someone is back", "cold": "The battery is cold and charges slower – the plan allows for it", "power_down": "Octopus session joined – the battery keeps power for it"},
    "de": {"away": "Niemand zu Hause – der Plan rechnet mit wenig Verbrauch, bis jemand zurück ist", "cold": "Die Batterie ist kalt und lädt langsamer – der Plan berücksichtigt das", "power_down": "Octopus-Session angemeldet – die Batterie hält Strom dafür bereit"},
    "fr": {"away": "Personne à la maison – le plan compte sur une faible consommation jusqu'au retour", "cold": "La batterie est froide et charge plus lentement – le plan en tient compte", "power_down": "Session Octopus rejointe – la batterie garde de l\'énergie pour elle"},
    "nl": {"away": "Niemand thuis – het plan rekent op weinig verbruik tot er iemand terug is", "cold": "De batterij is koud en laadt langzamer – het plan houdt er rekening mee", "power_down": "Octopus-sessie aangemeld – de batterij houdt stroom ervoor vast"},
    "sv": {"away": "Ingen hemma – planen räknar med låg förbrukning tills någon är tillbaka", "cold": "Batteriet är kallt och laddar långsammare – planen tar hänsyn till det", "power_down": "Octopus-session anmäld – batteriet sparar el till den"},
    "nb": {"away": "Ingen hjemme – planen regner med lavt forbruk til noen er tilbake", "cold": "Batteriet er kaldt og lader saktere – planen tar hensyn til det", "power_down": "Octopus-økt påmeldt – batteriet sparer strøm til den"},
}

DECISIONS = {
    "da": {
        "FREE_DISCHARGE": ("Batteriet forsyner huset", "discharge"), "DISCHARGE": ("Batteriet forsyner huset", "discharge"),
        "FREE_CHARGE": ("Batteriet lader", "charge"), "CHARGE": ("Batteriet lader", "charge"),
        "GRID_CHARGE": ("Lader batteriet med billig strøm", "grid"), "FREE_GRID_CHARGE": ("Lader batteriet med billig strøm", "grid"),
        "FREE_HOLD": ("Gemmer strømmen til senere", "hold"), "FREE_EXPORT": ("Sælger strøm fra batteriet", "export"), "HOLD": ("Gemmer strømmen til senere", "hold"),
        "SELL_SUN": ("Sælger solen – det giver mere end at gemme den", "export"),
        "NOOP": ("Alt kører som planlagt", "hold"),
        "CAR_HELP": ("Batteriet hjælper bilen – det fyldes igen, før huset får brug for det", "discharge"), "CAR_GRID": ("Bilen lader fra nettet – batteriet gemmes til huset", "hold"),
    },
    "en": {
        "FREE_DISCHARGE": ("The battery powers the house", "discharge"), "DISCHARGE": ("The battery powers the house", "discharge"),
        "FREE_CHARGE": ("The battery is charging", "charge"), "CHARGE": ("The battery is charging", "charge"),
        "GRID_CHARGE": ("Charging the battery with cheap power", "grid"), "FREE_GRID_CHARGE": ("Charging the battery with cheap power", "grid"),
        "FREE_HOLD": ("Saving the power for later", "hold"), "FREE_EXPORT": ("Selling power from the battery", "export"), "HOLD": ("Saving the power for later", "hold"),
        "SELL_SUN": ("Selling the sun – it pays more than storing it", "export"),
        "NOOP": ("Everything runs as planned", "hold"),
        "CAR_HELP": ("The battery helps the car – it fills up again before the house needs it", "discharge"), "CAR_GRID": ("The car charges from the grid – the battery is kept for the house", "hold"),
    },
    "de": {
        "FREE_DISCHARGE": ("Die Batterie versorgt das Haus", "discharge"), "DISCHARGE": ("Die Batterie versorgt das Haus", "discharge"),
        "FREE_CHARGE": ("Die Batterie lädt", "charge"), "CHARGE": ("Die Batterie lädt", "charge"),
        "GRID_CHARGE": ("Lädt die Batterie mit günstigem Strom", "grid"), "FREE_GRID_CHARGE": ("Lädt die Batterie mit günstigem Strom", "grid"),
        "FREE_HOLD": ("Hebt den Strom für später auf", "hold"), "FREE_EXPORT": ("Verkauft Strom aus der Batterie", "export"), "HOLD": ("Hebt den Strom für später auf", "hold"),
        "SELL_SUN": ("Verkauft die Sonne – das bringt mehr als speichern", "export"),
        "NOOP": ("Alles läuft nach Plan", "hold"),
        "CAR_HELP": ("Die Batterie hilft dem Auto – sie wird wieder voll, bevor das Haus sie braucht", "discharge"), "CAR_GRID": ("Das Auto lädt aus dem Netz – die Batterie bleibt fürs Haus", "hold"),
    },
    "fr": {
        "FREE_DISCHARGE": ("La batterie alimente la maison", "discharge"), "DISCHARGE": ("La batterie alimente la maison", "discharge"),
        "FREE_CHARGE": ("La batterie charge", "charge"), "CHARGE": ("La batterie charge", "charge"),
        "GRID_CHARGE": ("Charge la batterie avec de l'électricité bon marché", "grid"), "FREE_GRID_CHARGE": ("Charge la batterie avec de l'électricité bon marché", "grid"),
        "FREE_HOLD": ("Garde l'énergie pour plus tard", "hold"), "FREE_EXPORT": ("Vend l'énergie de la batterie", "export"), "HOLD": ("Garde l'énergie pour plus tard", "hold"),
        "SELL_SUN": ("Vend le soleil – plus rentable que le stocker", "export"),
        "NOOP": ("Tout se déroule comme prévu", "hold"),
        "CAR_HELP": ("La batterie aide la voiture – elle se remplit avant que la maison en ait besoin", "discharge"), "CAR_GRID": ("La voiture charge sur le réseau – la batterie est gardée pour la maison", "hold"),
    },
    "nl": {
        "FREE_DISCHARGE": ("De batterij voedt het huis", "discharge"), "DISCHARGE": ("De batterij voedt het huis", "discharge"),
        "FREE_CHARGE": ("De batterij laadt", "charge"), "CHARGE": ("De batterij laadt", "charge"),
        "GRID_CHARGE": ("Laadt de batterij met goedkope stroom", "grid"), "FREE_GRID_CHARGE": ("Laadt de batterij met goedkope stroom", "grid"),
        "FREE_HOLD": ("Bewaart de stroom voor later", "hold"), "FREE_EXPORT": ("Verkoopt stroom uit de batterij", "export"), "HOLD": ("Bewaart de stroom voor later", "hold"),
        "SELL_SUN": ("Verkoopt de zon – dat levert meer op dan opslaan", "export"),
        "NOOP": ("Alles loopt volgens plan", "hold"),
        "CAR_HELP": ("De batterij helpt de auto – hij is weer vol voordat het huis hem nodig heeft", "discharge"), "CAR_GRID": ("De auto laadt van het net – de batterij blijft voor het huis", "hold"),
    },
    "sv": {
        "FREE_DISCHARGE": ("Batteriet försörjer huset", "discharge"), "DISCHARGE": ("Batteriet försörjer huset", "discharge"),
        "FREE_CHARGE": ("Batteriet laddar", "charge"), "CHARGE": ("Batteriet laddar", "charge"),
        "GRID_CHARGE": ("Laddar batteriet med billig ström", "grid"), "FREE_GRID_CHARGE": ("Laddar batteriet med billig ström", "grid"),
        "FREE_HOLD": ("Sparar strömmen till senare", "hold"), "FREE_EXPORT": ("Säljer ström från batteriet", "export"), "HOLD": ("Sparar strömmen till senare", "hold"),
        "SELL_SUN": ("Säljer solen – det ger mer än att spara den", "export"),
        "NOOP": ("Allt går som planerat", "hold"),
        "CAR_HELP": ("Batteriet hjälper bilen – det fylls igen innan huset behöver det", "discharge"), "CAR_GRID": ("Bilen laddar från nätet – batteriet sparas till huset", "hold"),
    },
    "nb": {
        "FREE_DISCHARGE": ("Batteriet forsyner huset", "discharge"), "DISCHARGE": ("Batteriet forsyner huset", "discharge"),
        "FREE_CHARGE": ("Batteriet lader", "charge"), "CHARGE": ("Batteriet lader", "charge"),
        "GRID_CHARGE": ("Lader batteriet med billig strøm", "grid"), "FREE_GRID_CHARGE": ("Lader batteriet med billig strøm", "grid"),
        "FREE_HOLD": ("Sparer strømmen til senere", "hold"), "FREE_EXPORT": ("Selger strøm fra batteriet", "export"), "HOLD": ("Sparer strømmen til senere", "hold"),
        "SELL_SUN": ("Selger solen – det gir mer enn å lagre den", "export"),
        "NOOP": ("Alt går som planlagt", "hold"),
        "CAR_HELP": ("Batteriet hjelper bilen – det fylles igjen før huset trenger det", "discharge"), "CAR_GRID": ("Bilen lader fra nettet – batteriet spares til huset", "hold"),
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
    from . import energyrate

    if energyrate.is_energy(state):  # a kWh counter chosen as charging power (Monta): worked out from how fast it rises
        return energyrate.watts(str((state or {}).get("entity_id") or ""), state)
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
        self.sun_source: str | None = None  # where the plan's sun comes from: sensor, energy (dashboard), own

    async def async_detect(self) -> None:
        from .detect import detect

        try:
            self.detected = await detect(self.ha, ((self.settings.get("community") or {}).get("common") or {}).get("sensors"))
        except Exception:  # noqa: BLE001 - keep what was found before
            import logging

            logging.getLogger(__name__).warning("Finding the parts failed", exc_info=True)

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self.file.read_text())
        except (OSError, ValueError):
            return {"roles": {}, "battery_kwh": None, "import_limit_kw": 10}

    def save(self, changes: dict[str, Any], source: str | None = None) -> None:
        # Who changed what, when (the last 40): a setting that "moves by itself" shows where it came from in the diagnosis.
        if source:
            log = list(self.settings.get("change_log") or [])
            for key, value in changes.items():
                old = self.settings.get(key)
                if key != "roles" and not isinstance(value, (dict, list)) and value != old:
                    log.append({"t": datetime.now(ZoneInfo(self.ha.config.get("time_zone") or "UTC")).isoformat(timespec="seconds"), "key": key, "from": old, "to": value, "by": source})
            self.settings["change_log"] = log[-40:]
        for key, value in changes.items():
            if key == "roles":
                self.settings.setdefault("roles", {}).update({k: v for k, v in value.items() if k in ROLES})
            elif key in ("battery_kwh", "import_limit_kw", "language", "setup_done", "style", "price_area", "tariff", "markup", "price_source", "tou", "vat", "battery_min_soc", "grid_charge",
                         "sell", "sell_price", "solar_value", "ev_in_house", "battery_sign", "grid_sign", "grid_noise", "ev_follow_sun", "ev_fuse_guard",
                         "battery_export", "battery_no_export_cheap", "scene_fx", "battery_wear", "battery_care", "battery_type", "battery_price", "fuse_ok", "own_history", "things", "things_dismissed", "power_tariff_price", "power_tariff_kind", "battery_grid_max", "export_limit_kw", "agile_region", "restore_values",
                         "offgrid", "reserve_soc", "emergency_soc", "gen_stop_soc", "gen_charge_kw", "gen_min_run_h",
                         "quiet_gen_from", "quiet_gen_to", "battery_charge_kw", "battery_discharge_kw", "ev_mode", "charger_kw", "ev_need_kwh",
                         "quiet_from", "quiet_to", "quiet_battery", "quiet_car",
                         "quiet_battery_from", "quiet_battery_to", "quiet_car_from", "quiet_car_to",
                         "control", "inverter_profile", "custom_profile", "battery_takeover", "ev_now", "ev_target", "ev_sun_target", "ev_trip", "ev_battery_kwh", "charger_phases", "ev_ready", "ev_switch", "ev_phase_switch",
                         "batteries", "battery_dismissed", "chargers", "charger_dismissed", "battery_targets", "manual", "tariff_current", "tariff_show",
                         # the self-test and what was mended by itself (selftest.py, autofix.py)
                         "pd_joined", "selftest", "observed", "auto_test", "auto_tested", "self_tune", "profile_fixes", "test_skipped", "autofix_log", "autofix_ignore", "role_scale", "price_scale", "last_report",
                         # learning together (telemetry.py)
                         "install_id", "first_seen", "first_control", "share_anonymous", "share_hours", "companion_snooze", "telemetry_sent", "hours_sent_day", "community", "community_ignore", "replies", "replies_seen", "last_error", "replies_hidden", "replies_shown",
                         # the update card (telemetry.py)
                         "latest", "behind", "update_snooze", "update_told", "whatsnew_seen", "changelog_for", "changelog_remote",
                         # stop selling at negative prices (curtail.py)
                         "curtail", "curtail_saved", "curtail_test", "share_full",
                         # storm watch (storm.py)
                         "storm", "storm_gust", "storm_soc", "storm_hold", "readonly_dismissed",
                         # the session meter at plug-in (async_plug_marks)
                         "plug_marks", "sell_sun",
                         # which savings the card shows (battery / sun and battery)
                         "saved_view", "report_notes",
                         # "No thanks" on the automatic-updates card (autoupdate.py)
                         "autoupdate_no"):
                self.settings[key] = value
        self.file.write_text(json.dumps(self.settings, indent=2))

    # ---------- finding the parts ----------

    def _price_now_from_rates(self) -> float | None:
        """An event entity (Octopus' current day rates) has no number as its state: the slot now from its rates."""
        from .pricefeed import now_price

        return now_price(self.ha.states, self.role("price"), ZoneInfo(self.ha.config.get("time_zone") or "UTC"), self.price_scale())

    def grid_sign(self) -> int:
        """+1: positive grid power is buying (most meters). -1: positive is selling (Solis/SolaX PCC …). Chosen, or found."""
        if getattr(self, "ha", None) is not None and self.grid_pair():
            return 1  # buying less selling: always positive when buying
        chosen = self.settings.get("grid_sign")
        if chosen in (1, -1):
            return chosen
        return self.grid_sign_found() or 1

    def grid_sign_found(self) -> int | None:
        """Found from the house's own balance: with the battery resting, what the grid gives is house - sun."""
        votes = list(getattr(self, "_grid_votes", []))
        s = sum(votes)
        if len(votes) >= 8 and abs(s) >= 0.6 * len(votes):
            return 1 if s > 0 else -1
        # Not found from the balance (no house sensor, say): what the integration is known to do. GoodWe's meter
        # counts selling as plus (a user in New Zealand had to turn it by hand).
        reg = getattr(getattr(self, "controller", None), "_ent_reg", None) or {}
        e = self.role("grid_power") if reg else None
        if e and (reg.get(e) or {}).get("platform") in GRID_SELL_PLUS:
            return -1
        return None

    def _watch_grid(self, raw: float | None, house: float | None, pv: float | None, batt: float | None, ev: float | None) -> None:
        if raw is None or house is None or pv is None or (batt is not None and abs(batt) > 150) or abs(raw) < 150:
            return
        expected = house - pv + (0.0 if (self.engine and self.engine.ev_in_house()) else (ev or 0.0))
        if abs(expected) < 150:
            return
        if abs(raw - expected) < 0.35 * abs(expected):
            vote = 1
        elif abs(raw + expected) < 0.35 * abs(expected):
            vote = -1
        else:
            return  # doesn't add up either way - another sensor is off, don't guess
        from collections import deque

        if not hasattr(self, "_grid_votes"):
            self._grid_votes = deque(maxlen=30)
        self._grid_votes.append(vote)

    def sell_sun(self) -> bool:
        """"Sell the sun instead of storing it" - on for new installs, off for those who had Energy Pilot before
        (they are offered it, so the battery doesn't suddenly behave otherwise)."""
        if "sell_sun" in self.settings:
            return bool(self.settings["sell_sun"])
        return str(self.settings.get("first_seen") or "") >= "2026-11-17"

    def price_scale(self) -> float:
        """1, or 0.01 when the price sensor gives øre/cents (found by autofix.py)."""
        return float(self.settings.get("price_scale") or 1.0)

    def scaled(self, role: str, v: float | None) -> float | None:
        """A sensor read the right way: a battery level given as 0-1, or kW without saying so (autofix.py)."""
        k = (self.settings.get("role_scale") or {}).get(role)
        return v * k if v is not None and k else v

    def _battery_eff(self) -> int | None:
        """The round-trip efficiency the plan uses now (learned, or the datasheet's), in % - shown with "why it holds"."""
        try:
            return round(self.engine.settings().efficiency * 100) if self.engine else None
        except Exception:  # noqa: BLE001 - only a hint on the front page
            return None

    def sun_store(self, flow: dict[str, Any], plan: dict[str, Any] | None, now: datetime | None = None) -> dict[str, Any] | None:
        """Why the sun goes into the battery instead of being sold: the stored kWh is worth more later (sold or used in the
        house) than the feed-in price now, after the battery's loss. None when the sun isn't being stored or selling is off."""
        try:
            if not self.engine or not self.settings.get("sell"):
                return None
            pv, house, batt = (flow or {}).get("pv"), (flow or {}).get("house"), (flow or {}).get("battery")
            if pv is None or batt is None or batt < 50 or pv - (house or 0) < 50:
                return None  # not charging from a sun surplus
            res = (self.engine.result or {}).get("battery") or {}
            steps, slot = res.get("steps") or [], timedelta(minutes=res.get("slot_min") or 60)
            now = now or datetime.now(ZoneInfo(self.ha.config.get("time_zone") or "UTC"))
            sells, fixed = self.engine.sell_prices(), float(self.settings.get("sell_price") or 0)
            sell_now = self.engine.sell_at(sells, now, fixed)
            hour = {datetime.fromisoformat(h["t"]): h["price"] for h in (plan or {}).get("hours") or [] if h.get("price") is not None}
            use = []  # (start, worth) of every later slot the battery gives power in
            for st in steps:
                t = datetime.fromisoformat(st["t"])
                if t <= now or st.get("action") not in ("export", "discharge"):
                    continue
                v = self.engine.sell_at(sells, t, fixed) if st["action"] == "export" else hour.get(t.replace(minute=0, second=0, microsecond=0))
                if v is not None:
                    use.append((t, v))
            if not use or sell_now is None:
                return None
            top = max(v for _, v in use)
            if top * self.engine.settings().efficiency <= sell_now:
                return None  # selling now would pay as well: nothing to explain
            runs: list[list[datetime]] = []  # the dear slots in unbroken runs; the longest is shown (the evening, not one odd slot)
            for t in sorted(t for t, v in use if v >= top * 0.9):
                if runs and t - runs[-1][-1] == slot:
                    runs[-1].append(t)
                else:
                    runs.append([t])
            run = max(runs, key=len)
            return {"now": sell_now, "p": top, "from": run[0].isoformat(), "to": (run[-1] + slot).isoformat()}
        except Exception:  # noqa: BLE001 - only a hint on the front page
            return None

    def battery_pair(self) -> tuple[str, str] | None:
        """(charge, discharge) when the battery's power is two sensors that each show one way only - Fox ESS Modbus
        has "Battery Charge" and "Battery Discharge", both 0 or more. Then the power is charge less discharge."""
        e = self.role("battery_power") or ""
        m = re.match(r"^(sensor\..*battery_)(dis)?charge(_power)?$", e)
        if not m:
            return None
        other = m.group(1) + ("" if m.group(2) else "dis") + "charge" + (m.group(3) or "")
        if other not in self.ha.states:
            return None
        return (other, e) if m.group(2) else (e, other)

    def grid_pair(self) -> tuple[str, str] | None:
        """(buying, selling) when the grid's power is two sensors that each show one way only - Fox ESS Modbus has
        "Grid Consumption" and "Feed-in", others "import" and "export" power. Then the power is buying less selling;
        with the buying one alone, selling never showed (a user in the UK: "Export not shown")."""
        e = self.role("grid_power") or ""
        if not e.startswith("sensor.") or re.search(r"(^|[._])net([._]|$)|import_export|export_import", e):
            return None
        for buy, sell in (("grid_consumption", "feed_in"), ("consumption", "feed_in"), ("import", "export")):
            if buy in e and (other := e.replace(buy, sell, 1)) in self.ha.states:
                return e, other
        return None

    def battery_sign(self) -> int:
        """+1: positive battery power is charging (Growatt). -1: positive is discharging (Fox ESS). Chosen, or found."""
        if self.battery_pair():
            return 1  # charge less discharge: always positive when charging
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

    async def async_plug_marks(self) -> None:
        """For each charger with a plug and a session meter: what the meter showed when the car was plugged in -
        read from the history at that moment, kept until the car is unplugged (see chargers.session)."""
        from . import chargers

        pairs = [(self.role("ev_plug"), self.role("ev_session"))]
        pairs += [(c.get("plug"), c.get("session")) for c in chargers.extras(self.settings)]
        marks = dict(self.settings.get("plug_marks") or {})
        changed = False
        for plug_e, session_e in pairs:
            if not plug_e or not session_e:
                continue
            if not chargers.is_plugged((self.ha.states.get(plug_e) or {}).get("state")):
                changed |= marks.pop(plug_e, None) is not None
                continue
            if plug_e in marks:
                continue
            value = await self._meter_at_plug_in(plug_e, session_e)
            if value is not None:
                marks[plug_e], changed = value, True
        if changed:
            self.save({"plug_marks": marks})

    async def _meter_at_plug_in(self, plug_e: str, session_e: str) -> float | None:
        from . import chargers

        start = (datetime.now(ZoneInfo("UTC")) - timedelta(days=3)).isoformat()
        try:
            res = await self.ha.command({"type": "history/history_during_period", "start_time": start, "entity_ids": [plug_e],
                                         "minimal_response": True, "no_attributes": True, "significant_changes_only": False})
            rows = (res or {}).get(plug_e) or []
            at = None
            for prev, row in zip([None, *rows], rows):  # the last time it went from out to in
                if chargers.is_plugged(row.get("s")) and (prev is None or not chargers.is_plugged(prev.get("s"))):
                    at = row.get("lu") or row.get("lc")
            if at is None:
                return None
            when = datetime.fromtimestamp(float(at), ZoneInfo("UTC")).isoformat()
            res = await self.ha.command({"type": "history/history_during_period", "start_time": when, "entity_ids": [session_e],
                                         "minimal_response": True, "no_attributes": True, "include_start_time_state": True})
            first = ((res or {}).get(session_e) or [{}])[0]
            return float(first.get("s"))
        except Exception:  # noqa: BLE001 - no history: the last-changed rule decides
            return None

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
        if name == "battery_soc" and chosen in self._phones():
            chosen = None  # a phone's battery is never the house battery (one was picked, and nothing was controlled)
        if chosen and chosen in states and not (name in ("price", "sell_price") and chosen.split(".")[0] not in PRICE_DOMAINS):
            return chosen  # (a price is never an update, a button or a switch - such a pick is passed over)
        spec = ROLES[name]
        for e in spec["known"]:
            if e in states and states[e].get("state") not in ("unavailable", "unknown", None):
                return e
        found = (self.detected.get(name) or {}).get("entity_id")
        return found if found in states else None

    def source(self, name: str) -> str | None:
        """Where a part was found: "chosen", "known", "energy", "integration:<platform>", "name" or "computed"."""
        chosen = (self.settings.get("roles") or {}).get(name)
        if chosen and not (name == "battery_soc" and chosen in self._phones()):
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

    def _phones(self) -> set[str]:
        """Phones' and tablets' entities (the Companion app), known once the controller has read the registry."""
        return getattr(getattr(self, "controller", None), "phones", None) or set()

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
                    # A charger without live power (Monta): its kWh counter can be picked - the power is worked out.
                    if not (name == "ev_power" and domain == "sensor" and unit in ("kwh", "wh")
                            and a.get("state_class") in ("total_increasing", "total")):
                        continue
                if cls == "battery" and not (dc == "battery" or (domain == "sensor" and not dc and unit == "%")):
                    continue
                if name == "battery_soc" and e in self._phones():
                    continue  # a phone is not the house battery
                # A binary plug sensor, or a charger's status list (VEVOR, OCPP …) that says when the car is in.
                if cls == "plug" and not ((domain == "binary_sensor" and dc in ("plug", "power", None))
                                          or (domain == "sensor" and dc == "enum")):
                    continue
                if cls == "energy" and not (dc == "energy" or (domain == "sensor" and not dc and unit in ("kwh", "wh"))):
                    continue
                if name in ("price", "sell_price") and domain not in PRICE_DOMAINS:
                    continue  # "update.tibber_price_…" is named like a price but holds none
                guess = e in spec["known"] or any(w in e for w in spec["words"])
                if name == "ev_soc":
                    # Cars' levels first; other % sensors may still be picked by hand (a template, MQTT …).
                    guess = e in str((self.detected.get("_ev_soc_options") or {}).get("entity_id", "")).split()
                    if not guess and (a.get("unit_of_measurement") != "%" or e == self.role("battery_soc")):
                        continue
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
        pv = self.scaled("pv_power", sum(arrays) if arrays else None)  # several arrays are added up
        house = self.scaled("house_power", _watts(st.get(r["house_power"])) if r["house_power"] else None)
        batt = self.scaled("battery_power", _watts(st.get(r["battery_power"])) if r["battery_power"] else None)
        if (pair := self.battery_pair()) is not None:
            c, d = (self.scaled("battery_power", _watts(st.get(x))) for x in pair)
            batt = None if c is None and d is None else (c or 0) - (d or 0)
        elif batt is not None:
            batt *= self.battery_sign()  # some integrations (Fox ESS Modbus …) count discharging as positive
        soc = self.scaled("battery_soc", _num(st.get(r["battery_soc"])) if r["battery_soc"] else None)
        packs = None
        from . import batteries

        if more := batteries.extras(self.settings):
            # More than one battery: the plan sees one - the level weighted by size, the powers added up.
            main = {"name": "", "soc": soc, "power": batt, "kwh": self.main_battery_kwh()}
            others = [batteries.read(st, b) for b in more]
            soc, batt = batteries.combine(main, others)
            packs = [main] + others
        grid = self.scaled("grid_power", _watts(st.get(r["grid_power"])) if r["grid_power"] else None)
        if (gpair := self.grid_pair()) is not None:
            b, s_ = (self.scaled("grid_power", _watts(st.get(x))) for x in gpair)
            grid = None if b is None and s_ is None else (b or 0) - (s_ or 0)
        if grid is not None:
            self._watch_grid(grid, house, pv, batt, self.scaled("ev_power", _watts(st.get(r["ev_power"])) if r["ev_power"] else None))
            grid *= self.grid_sign()  # some meters (Solis/SolaX PCC …) count buying as negative
        ev = self.scaled("ev_power", _watts(st.get(r["ev_power"])) if r["ev_power"] else None)
        from . import chargers

        plug = chargers.is_plugged((st.get(r["ev_plug"]) or {}).get("state")) if r["ev_plug"] else None
        if plug is None and self.settings.get("ev_switch"):
            plug = True  # a plain switch (a smart plug) can't tell whether a car is in: taken as plugged in, or it never turns on

        cars = [chargers.read(st, c, self.settings.get("plug_marks")) for c in chargers.extras(self.settings)] or None
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
        first = (b.get("steps") or [{}])[0]
        if key == "FREE_HOLD" and (first.get("grid") or 0) < -0.01 and self.sell_sun() and self.controller and self.controller.can_block_sun():
            key = "SELL_SUN"  # the sun's surplus is sold, not stored
        if ((self.flow() or {}).get("ev") or 0) > 1000 and key in ("FREE_DISCHARGE", "FREE_HOLD"):
            key = "CAR_HELP" if key == "FREE_DISCHARGE" else "CAR_GRID"  # the car charging: what the battery does for it
        text, kind = DECISIONS.get(lang, DECISIONS["en"]).get(key) or DECISIONS["en"][key]
        notes = NOTES.get(lang, NOTES["en"])
        return {"key": key, "text": text, "kind": kind, "reason": None, "target": b["target"], "plan": [], "engine": True,
                "saving": b["saving"], "blocked": self._not_discharging(key),
                "notes": [notes.get(n) or NOTES["en"].get(n, n) for n in getattr(self.engine, "notes", None) or []]}

    def _not_discharging(self, key: str) -> bool:
        """The plan says the battery covers the house, but for 5 minutes it has stood still while the house buys from
        the grid: the headline then says it is planned, not happening (something else holds the battery back)."""
        import time

        f = self.flow() or {}
        b, g, soc = f.get("battery"), f.get("grid"), f.get("soc")
        idle = key == "FREE_DISCHARGE" and b is not None and -50 < b < 50 and (g or 0) > 100 and (soc is None or soc > 15)
        if not idle:
            self._idle_since = None
            return False
        now = time.time()
        if getattr(self, "_idle_since", None) is None:
            self._idle_since = now
        return now - self._idle_since >= 300

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

    def runtime(self, plan: dict[str, Any], flow: dict[str, Any]) -> dict[str, Any] | None:
        """How long the battery lasts (runtime.py) - only with a battery."""
        if not self.engine or not ((flow or {}).get("has") or {}).get("battery"):
            return None
        from . import runtime

        try:
            b = self.engine.settings()
            tz = ZoneInfo(self.ha.config.get("time_zone") or "UTC")
            now = datetime.now(tz)
            res = self.engine.result or {}
            r = runtime.compute(plan, flow, b.capacity_kwh, b.min_soc, now, getattr(self.engine, "storm", None),
                                steps=(res.get("battery") or {}).get("steps"), events=self._rt_events(res, now),
                                sky=self._sky())
        except Exception:  # noqa: BLE001
            return None
        if r is not None:
            try:
                r["stats"] = self.engine.battstats.summary(now, b.min_soc) if getattr(self.engine, "battstats", None) else None
                r["sun_share"] = self.engine.ledger.summary(now).get("sun_share")
            except Exception:  # noqa: BLE001
                pass
        return r

    def _sky(self) -> dict[str, Any] | None:
        """Sunset and sunrise, from HA's own sun."""
        a = ((self.ha.states.get("sun.sun") or {}).get("attributes") or {})
        return {"set": a.get("next_setting"), "rise": a.get("next_rising")} if a.get("next_setting") else None

    def _rt_events(self, res: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
        """What else runs on the plan: the car's charges and the small things - an icon at each start."""
        out: list[dict[str, Any]] = []

        def starts(hours: list[str], icon: str) -> None:
            prev = None
            for t in sorted(hours or []):
                d = datetime.fromisoformat(t)
                if prev is None or (d - prev).total_seconds() > 3600:
                    out.append({"t": d.replace(minute=0).isoformat(), "icon": icon})
                prev = d

        starts((res.get("car") or {}).get("hours") or [], "🚗")
        for c in res.get("cars") or []:
            starts(c.get("hours") or [], "🚗")
        icons = {"dish": "🍽️", "dryer": "🌀", "wash": "🧺", "mower": "🌱", "bike": "🚲", "tool": "🔧"}
        try:
            for t in self.engine.things.view(self.settings, now) if self.settings.get("things") else []:
                ic = icons.get(t.get("icon"), "🔌")
                if t.get("start"):
                    out.append({"t": datetime.fromisoformat(t["start"]).replace(minute=0, second=0, microsecond=0).isoformat(), "icon": ic})
                else:
                    starts(t.get("hours") or [], ic)
        except Exception:  # noqa: BLE001
            pass
        return out

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
                                          (self.engine.service_prices if self.engine else []) or [], self.price_scale())
        self.fine_prices = prices  # quarter/half-hour prices as they come - the engine plans in those slots
        if not prices and not self.settings.get("offgrid"):
            self.price_info["none"] = True  # no prices at all (the market's data is late): the battery runs as normal
        if prices:
            buckets: dict[str, list[float]] = {}
            for dt, value in sorted(prices.items()):
                if (h := slot(dt)) is not None:
                    buckets.setdefault(h["t"], []).append(value)
            for key, h in hours.items():
                if h["t"] in buckets:
                    b = buckets[h["t"]]
                    h["price"] = round(sum(b) / len(b), 3)
                    if len(b) > 1 and max(b) - min(b) > 0.0005:
                        h["q"] = [round(v, 3) for v in b]  # the hour's quarters (or halves): the graphs draw each
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
                        try:  # Solcast's poor day (10 % chance of less): how sure the forecast is
                            h["sun10"] = round(h.get("sun10", 0.0) + min(kwh, float(p.get("pv_estimate10"))), 2)
                        except (TypeError, ValueError):
                            pass
        # Not every forecast sensor carries the hours (Solcast does): next the ones that carry them in another
        # shape (Open-Meteo Solar Forecast's wh_period), then Home Assistant's Energy dashboard forecast
        # (Forecast.Solar and the rest), and last its own learned forecast - so the plan always knows the sun.
        has_sun = any("sun" in h for h in hours.values())
        if not has_sun:
            per: dict[datetime, float] = {}
            for role in ("solar_today", "solar_tomorrow"):
                for e in self.role_all(role):
                    a = (self.ha.states.get(e) or {}).get("attributes") or {}
                    for t, wh in (a.get("wh_period") or {}).items() if isinstance(a.get("wh_period"), dict) else []:
                        try:
                            per[datetime.fromisoformat(str(t))] = float(wh) / 1000  # the same moment twice: once
                        except (TypeError, ValueError):
                            continue
            for dt, kwh in per.items():
                if (h := slot(dt)) is not None:
                    h["sun"] = round(h.get("sun", 0.0) + kwh, 3)
                    has_sun = True
        self.sun_source = "sensor" if has_sun else None
        if not has_sun and self.engine and getattr(self.engine, "ha_solar", None):
            for when, kwh in self.engine.ha_solar.items():
                if (h := slot(when)) is not None:
                    h["sun"] = round(h.get("sun", 0.0) + kwh, 2)
                    has_sun, self.sun_source = True, "energy"
        if not has_sun and self.engine and self.engine.own_solar:
            for when, kwh in self.engine.own_solar.items():
                if (h := slot(when)) is not None:
                    h["sun"] = kwh
                    self.sun_source = "own"
        if any("sun" in h for h in hours.values()):
            for h in hours.values():  # forecasts leave out the night (Forecast.Solar): no number is no sun
                h.setdefault("sun", 0.0)
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
        for k, v in (self.settings.get("manual") or {}).items():
            if k in hours:
                hours[k]["manual"] = v  # the user's own choice for that hour
        # The plan shows Energy Pilot's own charging; another system's plan (AppDaemon) is only compared.
        res = (self.engine.result if self.engine else None) or {}
        # For the detailed plan (Plan > Detailed plan): what the battery does, what is bought (+) or sold (-), and the
        # feed-in price that hour - a slot of a quarter hour adds to its hour.
        sells = self.engine.sell_prices() if self.engine and hasattr(self.engine, "sell_prices") else {}
        fixed_sell = float(self.settings.get("sell_price") or 0) if self.settings.get("sell") else 0.0
        for st in (res.get("battery") or {}).get("steps", []):
            if (h := slot(datetime.fromisoformat(st["t"]))) is not None:
                h["soc"] = st["soc"]
                h["grid"] = round(h.get("grid", 0.0) + float(st.get("grid") or 0.0), 3)
                if st["action"] != "hold" or "action" not in h:
                    h["action"] = st["action"]
                if "sell" not in h and self.engine is not None and hasattr(self.engine, "sell_at"):
                    try:
                        h["sell"] = round(self.engine.sell_at(sells, datetime.fromisoformat(st["t"]), fixed_sell), 3)
                    except Exception:  # noqa: BLE001 - the table just shows no feed-in price
                        pass
                if st["action"] in ("charge_grid", "charge_sun"):
                    h["charge"] = True
                elif st["action"] == "export":
                    h["export"] = True  # sells from the battery
        # What the cars take in each hour (kWh): full speed through the planned slots until what they need is in.
        from . import chargers

        # Only chargers Energy Pilot really runs: a charger in shadow is charged by something else (the car's own app,
        # Octopus, an automation), and Energy Pilot's guess at its slots would show charging that won't happen.
        ctl = getattr(self, "controller", None)
        running = (lambda part: ctl.mode(part) == "control") if ctl else (lambda part: False)
        cars = [(res.get("car"), self.engine.charger_kw() if self.engine and hasattr(self.engine, "charger_kw") else float(self.settings.get("charger_kw") or 7.4), "car")]
        cars += [(c, float(x.get("charger_kw") or 7.4), f"car{i + 2}") for i, (c, x) in enumerate(zip(res.get("cars") or [], chargers.extras(self.settings)))]
        # A charger in shadow: the charge Energy Pilot would have made (kept from when the car was plugged in), drawn
        # apart from real plans - to compare with what charges the car today, not as something that will happen.
        ghosts = (getattr(self.engine, "ghosts", None).s if self.engine and getattr(self.engine, "ghosts", None) else {})
        for _plan, kw, part in cars:
            g = (ghosts.get(part) or {}).get("plan")
            if running(part) or not g:
                continue
            left, step = float(g.get("need") or 0), float(g.get("slot_h") or 1)
            for t in g.get("hours") or []:
                if (h := slot(datetime.fromisoformat(t))) is not None:
                    h["car_ghost"] = True
                    got = min(float(g.get("kw") or kw) * step, left) if left > 0 else 0.0
                    left -= got
                    h["car_ghost_kwh"] = round(h.get("car_ghost_kwh", 0.0) + got, 2)
        for plan, kw, part in cars:
            if not running(part):
                continue
            left = float((plan or {}).get("need_kwh") or 0)
            step = int((plan or {}).get("slot_min") or 60) / 60
            for t in sorted((plan or {}).get("hours", [])):
                if (h := slot(datetime.fromisoformat(t))) is not None:
                    h["car"] = True
                    got = min(kw * step, left) if left > 0 else 0.0
                    left -= got
                    h["car_kwh"] = round(h.get("car_kwh", 0.0) + got, 2)
        # The engine's own forecast covers every planned hour: it fills what another forecast doesn't reach
        # (an AppDaemon forecast that only covers today).
        for row in res.get("house", []):
            if (h := slot(datetime.fromisoformat(row["t"]))) is not None:
                h.setdefault("house", row["kwh"])
        rows = sorted(hours.values(), key=lambda h: h["t"])
        prices = [p for h in rows if "price" in h for p in (h.get("q") or [h["price"]])]  # the quarters set the scale
        cheapest = sorted((h for h in rows if "price" in h and h["t"] >= now.replace(minute=0, second=0, microsecond=0).isoformat()),
                          key=lambda h: h["price"])[:3]
        return {"now": now.isoformat(), "hours": rows,
                "price_min": min(prices) if prices else None, "price_max": max(prices) if prices else None,
                "cheapest": sorted(h["t"] for h in cheapest)}

    def _ready_hm(self, value: Any) -> Any:
        """A "ready at" sensor as the local "HH:MM" the page shows: evcc's plan time is a whole timestamp in UTC
        ("2026-11-24T06:30:00+00:00" - shown as "2026-" before). A helper's "07:30:00" or an unreadable value is left
        as it is (the page shows its first five characters)."""
        from .engine import ready_time

        if not isinstance(value, str) or not re.match(r"\d{4}-\d{2}-\d{2}[T ]", value):
            return value
        hm = ready_time(value, datetime.now(ZoneInfo(self.ha.config.get("time_zone") or "UTC")))
        return f"{hm[0]:02d}:{hm[1]:02d}" if hm else None

    def ev(self) -> dict[str, Any] | None:
        r, st = self.roles(), self.ha.states
        if not (r["ev_power"] or r["ev_plug"]):
            return None

        def val(role: str) -> Any:
            return (st.get(r[role]) or {}).get("state") if r[role] else None

        from . import chargers

        # Without helpers of its own, the car's buttons are Energy Pilot's (its settings).
        return {"manual": val("ev_manual") == "on" if r["ev_manual"] else bool(self.settings.get("ev_now")),
                "ready": self._ready_hm(val("ev_ready")) if r["ev_ready"] else self.settings.get("ev_ready"),
                "cap": _num(st.get(r["ev_cap"])) if r["ev_cap"] else self.settings.get("ev_need_kwh"),
                "cap_max": ((st.get(r["ev_cap"]) or {}).get("attributes") or {}).get("max") if r["ev_cap"] else None,
                "session_kwh": chargers.session(st, r["ev_session"], r["ev_plug"],
                                                (self.settings.get("plug_marks") or {}).get(r["ev_plug"] or "")),
                **self._ev_soc(), "charge": self._ev_charge(),
                "entities": {k: r[k] for k in ("ev_manual", "ev_ready", "ev_cap", "ev_soc")}}

    def _ev_charge(self) -> dict[str, Any] | None:
        """This charge so far (while plugged in): kWh, what it cost, and how much of it the sun gave."""
        g = getattr(self.engine, "ghosts", None) if self.engine else None
        own = (g.part("car").get("own") if g else None) or {}
        if not own.get("kwh"):
            return None
        return {"kwh": round(own["kwh"], 2), "cost": round(own.get("cost", 0.0), 2),
                "sun": round(min(1.0, own.get("sun_kwh", 0.0) / own["kwh"]), 2)}

    def _ev_soc(self) -> dict[str, Any]:
        """The car's own level and the target it charges to (see evsoc.py)."""
        from . import evsoc

        e = self.role("ev_soc")
        soc = evsoc.num(self.ha.states.get(e)) if e else None
        size = self.engine.car_size.kwh(self.settings) if self.engine and hasattr(self.engine, "car_size") else (evsoc.DEFAULT_KWH, "guess")
        if size[1] == "guess" and (c := evsoc.charger_kwh(self.ha.states)):
            size = (c, "charger")  # what the charger (evcc) knows of the car, until it is learned or set
        return {"soc": soc, "soc_known": e is not None, "target": evsoc.target(self.settings), "trip": bool(self.settings.get("ev_trip")),
                "sun_target": evsoc.sun_target(self.settings), "sun_target_set": bool(self.settings.get("ev_sun_target")),
                "has_sun": bool(self.role("pv_power")),
                "everyday": evsoc.target({**self.settings, "ev_trip": False}), "car_kwh": size[0], "car_kwh_from": size[1],
                "charge_kw_seen": self.engine.car_size.charge_kw() if self.engine and hasattr(self.engine, "car_size") else None}

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
            "flow": (fl := self.flow()), "decision": self.decision(lang), "plan": (pl := self.plan()), "ev": self.ev(),
            "runtime": self.runtime(pl, fl),
            "price": {"now": _num(price) if _num(price) is not None else self._price_now_from_rates(),
                      "unit": ((price or {}).get("attributes") or {}).get("unit_of_measurement")},
            # Home today: the engine's own (what the plan uses); another system's forecast is shown beside it.
            "solar": solar,
            "house_today": (self.engine.house_today() if self.engine else None)
            or (_num(self.ha.states.get(house_e)) if house_e else None),
            "house_other": _num(self.ha.states.get(house_e)) if house_e and self.engine and self.engine.house_today() else None,
            "house_other_appdaemon": bool(house_e and "appdaemon" in house_e),
            "settings": self.settings,
            "battery_eff": self._battery_eff(),
            "sun_store": self.sun_store(fl, pl),
            "sell_sun": {"on": self.sell_sun(), "can": bool(getattr(self, "controller", None) and self.controller.can_block_sun())},
            "scene": self._scene(),
            "ghosts": self.engine.ghosts.view() if self.engine and getattr(self.engine, "ghosts", None) else {},
        }

    def _scene(self) -> dict[str, Any] | None:
        """The weather, the time of day, the season and the holiday for the flow card (off in the settings: None)."""
        if self.settings.get("scene_fx") is False:
            return None
        from . import scene

        try:
            return scene.build(self.ha.states, self.ha.config, datetime.now(ZoneInfo(self.ha.config.get("time_zone") or "UTC")))
        except Exception:  # noqa: BLE001 - decoration never breaks the page
            return None

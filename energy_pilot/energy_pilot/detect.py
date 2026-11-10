"""Finding what a home has, without being told: sun, battery, grid, house, car charger, prices, forecasts.

In this order, the first that gives an answer wins for each part:
1. Home Assistant's Energy dashboard (many have already picked solar, battery and grid there) - from its energy
   sensors to the power sensors on the same device.
2. Known integrations: price (Strømligning, Nord Pool, Energi Data Service, Tibber, …), solar forecast (Solcast,
   Forecast.Solar, …), chargers (KEBA, Easee, Zaptec, go-e, Wallbox, OCPP, …) and inverters (Growatt, Huawei,
   SolarEdge, Victron, GivEnergy, …).
3. Names and kinds: a power sensor called "…pv_power" is the sun, "…battery…state_of_charge" the battery level.

Every answer says where it came from, so the guide can show it ("found in your Energy dashboard").
"""

from __future__ import annotations

import logging
import re
from typing import Any

_LOGGER = logging.getLogger(__name__)

PRICE = ("stromligning", "nordpool", "energidataservice", "tibber", "octopus_energy", "entsoe", "easyenergy", "frank_energie",
         "awattar", "zonneplan_one", "amber", "elering")
SOLAR_FORECAST = ("solcast_solar", "forecast_solar", "open_meteo_solar_forecast", "solarman_forecast")
CHARGERS = ("keba", "easee", "zaptec", "goecharger", "go_e", "goe_charger", "wallbox", "ocpp", "ohme", "myenergi",
            "tesla_wall_connector", "evse_wifi", "openevse", "peblar", "alfen_wallbox", "v2c")
INVERTERS = ("growatt_server", "huawei_solar", "solaredge", "solaredge_modbus_multi", "victron", "victron_ble", "givenergy",
             "givenergy_local", "sungrow", "solax", "solax_modbus", "foxess", "foxess_modbus", "sofar", "fronius",
             "enphase_envoy", "goodwe", "sma", "deye", "solarman", "sunsynk", "growatt_local", "huawei_solar_modbus")
# Platforms whose "battery" is a phone's or a sensor's, never a home battery.
NOT_HOME_BATTERY = ("mobile_app", "zha", "matter", "mqtt_room", "ble_monitor", "bthome", "switchbot", "homekit_controller",
                    "eufy_security", "roborock", "ecovacs", "xiaomi_ble", "tado", "netatmo", "nest", "ring", "hue",
                    # Cars: their battery level is not the house battery (an ID. Buzz was taken for one)
                    "volkswagen_we_connect_id", "volkswagencarnet", "tesla", "tesla_fleet", "teslemetry", "tessie",
                    "bmw_connected_drive", "renault", "kia_uvo", "hyundai_kia_connect", "mercedes_me", "mbapi2020",
                    "polestar_api", "myskoda", "skodaconnect", "audiconnect", "nissan_leaf", "fordpass", "toyota",
                    "volvo", "volvooncall", "stellantis_vehicles", "smartcar", "seatconnect", "cupra_we_connect",
                    "jlrincontrol", "porscheconnect", "zoe", "leaf", "evcc_intg")

# The car's own battery level ("ev_soc"): only from a car's integration (or a device a car maker made), never by name
# alone - a phone, a watch, a Zigbee sensor, the house battery or the car's 12 V battery are all "battery %".
CAR_PLATFORMS = ("tesla", "tesla_custom", "tesla_fleet", "teslemetry", "tessie", "volkswagen_we_connect_id", "volkswagencarnet",
                 "myskoda", "skodaconnect", "audiconnect", "seatconnect", "cupra_we_connect", "porscheconnect",
                 "bmw_connected_drive", "mercedes_me", "mbapi2020", "kia_uvo", "hyundai_kia_connect", "renault", "zoe",
                 "nissan_leaf", "leaf", "polestar_api", "polestar", "volvo", "volvooncall", "volvo_cars", "fordpass",
                 "toyota", "stellantis_vehicles", "smartcar", "jlrincontrol", "mg_saic", "saic_ismart", "byd", "smart_hashtag",
                 "rivian", "lucid", "zeekr", "subaru", "mazda", "honda", "evcc_intg", "ocpp", "tronity", "carconnectivity")
CAR_BRANDS = re.compile(r"\b(tesla|volkswagen|vw|audi|skoda|škoda|seat|cupra|porsche|bmw|mercedes|kia|hyundai|renault|dacia|"
                        r"nissan|polestar|volvo|ford|toyota|lexus|peugeot|citro[eë]n|opel|vauxhall|ds automobiles|fiat|jeep|saic motor|"
                        r"byd|zeekr|xpeng|rivian|lucid|jaguar|land rover|honda|mazda|subaru|genesis|lynk)\b", re.I)
EV_SOC_WORDS = re.compile(r"state_of_charge|battery_level|\bsoc\b|_soc$|charge_level|battery_percent|ev_battery|hv_battery|"
                          r"battery_charge|ladestand|ladezustand|niveau_de_charge|batteriniveau|laddniva", re.I)
EV_SOC_NOT = re.compile(r"12v|12_v|car_battery|aux|auxiliary|lv_battery|low_voltage|starter|key|fob|phone|watch|tyre|tire|fuel|range|"
                        r"target|limit|min|max|setpoint|health|soh|temperature|temp|signal|rssi|wifi|sentry|charge_rate|"
                        r"remote|tag|tracker|predicted|forecast|estimate|at_departure|departure", re.I)


def car_socs(entities: list[dict[str, Any]], devices: list[dict[str, Any]], states: dict[str, Any]) -> list[dict[str, Any]]:
    """The cars' battery levels found: [{"entity_id", "device", "score"}], best first. A sensor in %, 0-100, from a car
    integration or a device made by a car maker, named like a battery level - and none of the look-alikes."""
    makers = {d["id"]: f"{d.get('manufacturer') or ''} {d.get('model') or ''}" for d in devices}
    out = []
    for e in entities:
        eid, platform, dev = e["entity_id"], e.get("platform"), e.get("device_id")
        if not eid.startswith("sensor.") or e.get("disabled_by"):
            continue
        s = states.get(eid) or {}
        a = s.get("attributes") or {}
        if a.get("unit_of_measurement") != "%":
            continue
        car = platform in CAR_PLATFORMS or bool(dev and CAR_BRANDS.search(makers.get(dev, "")))
        if not car or platform in GADGETS:  # a phone or a sensor on a device a car maker's name matches is still that
            continue
        text = f"{eid} {a.get('friendly_name', '')}"
        # Always named like the driving battery: a plain "battery" with device class battery is often the 12 V one (Ford).
        if EV_SOC_NOT.search(text) or not EV_SOC_WORDS.search(text):
            continue
        try:
            v = float(s.get("state"))
            if not 0 <= v <= 100:
                continue
        except (TypeError, ValueError):
            if s.get("state") not in ("unavailable", "unknown"):
                continue  # a car asleep may be unknown for a while - that's fine
        score = 2 * (a.get("device_class") == "battery") + 2 * bool(re.search(r"state_of_charge|battery_level|\bsoc\b|_soc$", eid)) \
            + (platform in CAR_PLATFORMS) - (platform == "ocpp")  # the car's own app knows best; a charger only while it charges
        out.append({"entity_id": eid, "device": dev or eid, "score": score})
    return sorted(out, key=lambda r: -r["score"])


GADGETS = ("mobile_app", "zha", "zwave_js", "matter", "mqtt_room", "ble_monitor", "bthome", "switchbot", "homekit_controller",
           "xiaomi_ble", "hue", "deconz", "tuya", "shelly", "esphome_ble", "bluetooth", "ibeacon", "private_ble_device")

WORDS = {
    "pv_power": [r"\bpv\b|pv_power|pv_effekt|solar_power|solar_production|sol_produktion|input_power|photovoltaic"],
    "battery_power": [r"battery.*(power|effekt)|batteri.*(effekt|power)|charge_discharge_power"],
    "battery_soc": [r"state_of_charge|\bsoc\b|battery_level|batteri_niveau|battery_percentage"],
    "grid_power": [r"grid.*(power|effekt)|net.*(effekt|power)|meter_power|import_export|active_power_grid"],
    "house_power": [r"house|hus|home_(load|power|consumption)|load_power|forbrug|consumption_power"],
}
EXCLUDE = re.compile(r"forecast|prognose|today|daily|total|max|min|limit|setpoint|target|estimate|_rate$|cost|price")


async def detect(ha: Any) -> dict[str, dict[str, str]]:
    """{role: {"entity_id": …, "source": "energy" | "integration:<platform>" | "name"}}"""
    found: dict[str, dict[str, str]] = {}
    try:
        entities = await ha.command({"type": "config/entity_registry/list"})
        devices = await ha.command({"type": "config/device_registry/list"})
    except Exception:  # noqa: BLE001 - not allowed or old HA: names only
        entities, devices = [], []
    by_id = {e["entity_id"]: e for e in entities}
    on_device: dict[str, list[dict[str, Any]]] = {}
    for e in entities:
        if e.get("device_id") and not e.get("disabled_by"):
            on_device.setdefault(e["device_id"], []).append(e)
    dev_names = {d["id"]: (d.get("name_by_user") or d.get("name") or "") for d in devices}
    states = ha.states

    def attrs(entity_id: str) -> dict[str, Any]:
        return (states.get(entity_id) or {}).get("attributes") or {}

    def alive(entity_id: str) -> bool:
        return (states.get(entity_id) or {}).get("state") not in (None, "unavailable", "unknown")

    def sibling(entity_id: str, device_class: str, words: str | None = None) -> str | None:
        """A sensor of this device class on the same device as entity_id."""
        dev = (by_id.get(entity_id) or {}).get("device_id")
        best = None
        for e in on_device.get(dev, []):
            eid = e["entity_id"]
            if eid.startswith("sensor.") and attrs(eid).get("device_class") == device_class and alive(eid):
                if words is None or re.search(words, eid):
                    return eid
                best = best or eid
        return best

    def put(role: str, entity_id: str | None, source: str) -> None:
        if entity_id and role not in found and entity_id in states:
            found[role] = {"entity_id": entity_id, "source": source}

    # 1. The Energy dashboard.
    try:
        prefs = await ha.command({"type": "energy/get_prefs"})
    except Exception:  # noqa: BLE001
        prefs = {}
    for src in prefs.get("energy_sources") or []:
        kind = src.get("type")
        if kind == "solar":
            put("pv_power", src.get("stat_rate") or sibling(src.get("stat_energy_from", ""), "power", r"pv|solar|sol"), "energy")
        elif kind == "battery":
            put("battery_power", src.get("stat_rate") or sibling(src.get("stat_energy_from", ""), "power", r"batt"), "energy")
            put("battery_soc", sibling(src.get("stat_energy_from", ""), "battery"), "energy")
        elif kind == "grid":
            put("grid_power", src.get("stat_rate") or sibling(((src.get("flow_from") or [{}])[0]).get("stat_energy_from", ""), "power"), "energy")
            price = ((src.get("flow_from") or [{}])[0]).get("entity_energy_price")
            put("price", price, "energy")
    for dev in prefs.get("device_consumption") or []:
        stat = dev.get("stat_consumption", "")
        platform = (by_id.get(stat) or {}).get("platform")
        if platform in CHARGERS or re.search(r"charg|lader|wallbox|ev_|elbil", stat):
            put("ev_power", dev.get("stat_rate") or sibling(stat, "power"), "energy")

    # 2. Known integrations.
    prices: list[tuple[int, str, str]] = []
    for e in entities:
        eid, platform = e["entity_id"], e.get("platform")
        if e.get("disabled_by") or not alive(eid):
            continue
        a = attrs(eid)
        if platform in PRICE and eid.startswith("sensor.") and str(a.get("unit_of_measurement", "")).lower().endswith("/kwh"):
            # The one with the coming prices, preferably the price you pay (with tax).
            if any(isinstance(a.get(k), list) for k in ("prices", "raw_today", "forecast", "today")):
                score = 3 if re.search(r"current|aktuel", eid) else 2 if re.search(r"total", eid) else 1
                prices.append((score, -len(eid), eid, platform))
        elif platform in SOLAR_FORECAST and eid.startswith("sensor."):
            if "peak" in eid or "remaining" in eid:
                continue
            if re.search(r"forecast_today$|energy_production_today$|production_today$", eid):
                put("solar_today", eid, f"integration:{platform}")
            elif re.search(r"forecast_tomorrow$|energy_production_tomorrow$|production_tomorrow$", eid):
                put("solar_tomorrow", eid, f"integration:{platform}")
        elif platform in CHARGERS:
            if eid.startswith("sensor.") and a.get("device_class") == "power" and not EXCLUDE.search(eid):
                put("ev_power", eid, f"integration:{platform}")
            elif eid.startswith("binary_sensor.") and (a.get("device_class") == "plug" or re.search(r"plug|cable|stik", eid)):
                put("ev_plug", eid, f"integration:{platform}")
            elif eid.startswith("sensor.") and re.search(r"session_energy|session|energy_charged|added_energy", eid):
                put("ev_session", eid, f"integration:{platform}")
        elif platform in INVERTERS and eid.startswith("sensor."):
            for role, patterns in WORDS.items():
                cls = "battery" if role == "battery_soc" else "power"
                if a.get("device_class") == cls and re.search(patterns[0], eid) and not EXCLUDE.search(eid):
                    put(role, eid, f"integration:{platform}")

    if prices:
        _score, _len, eid, platform = max(prices)
        put("price", eid, f"integration:{platform}")

    # The car's battery level: picked by itself only when there is one car - with two, the user says which charges here.
    cars = car_socs(entities, devices, states)
    if cars:
        found["_ev_soc_options"] = {"entity_id": " ".join(c["entity_id"] for c in cars), "source": "options"}
        own = [c for c in cars if c["device"] == cars[0]["device"]]
        if len({c["device"] for c in cars if c["score"] >= 2}) <= 1:
            platform = (by_id.get(own[0]["entity_id"]) or {}).get("platform")
            put("ev_soc", own[0]["entity_id"], f"integration:{platform}")

    # 3. Names and kinds (inverters through MQTT, Modbus, templates …).
    for role, patterns in WORDS.items():
        if role in found:
            continue
        cls = "battery" if role == "battery_soc" else "power"
        best: tuple[int, str] | None = None
        for eid, s in states.items():
            if not eid.startswith("sensor.") or not alive(eid):
                continue
            a = s.get("attributes") or {}
            if a.get("device_class") != cls or EXCLUDE.search(eid):
                continue
            platform = (by_id.get(eid) or {}).get("platform")
            if role == "battery_soc" and (platform in NOT_HOME_BATTERY or a.get("unit_of_measurement") != "%"):
                continue
            text = f"{eid} {a.get('friendly_name', '')} {dev_names.get((by_id.get(eid) or {}).get('device_id'), '')}".lower()
            if not re.search(patterns[0], text):
                continue
            # Inverter words make it likelier; car/phone words make it unlikely.
            score = 1 + bool(re.search(r"growatt|huawei|solaredge|victron|inverter|sph|sungrow|goodwe|fronius|deye|foxess|solax", text))
            score -= 2 * bool(re.search(r"car|bil|tesla|phone|telefon|ipad|watch|laptop|ups", text))
            if role == "house_power" and re.search(r"uden_bil|without_ev|excl", text):
                score += 1
            # The plain names inverters use win over look-alikes ("grid to battery" is neither).
            if re.search({"pv_power": r"pv_power", "battery_power": r"battery_power", "grid_power": r"grid_power",
                          "house_power": r"load_power|house_power", "battery_soc": r"state_of_charge"}[role], eid):
                score += 2
            if role in ("battery_power", "grid_power") and re.search(r"net_til|_til_|_to_|from_grid|grid_to|to_battery", eid):
                score -= 3
            if best is None or score > best[0]:
                best = (score, eid)
        if best and best[0] > 0:
            put(role, best[1], "name")
    return found

"""Telling an inverter and a charger what to do - the same few intents for every brand.

Battery intents:
- "normal": the house first; the battery covers the house and stores solar surplus (self-use)
- "hold": keep what is in the battery (no discharging); solar may still fill it
- "charge": charge from the grid now, at a power, up to a target level

Charger intents: "charge" at a current (A), or "stop".

Each brand is a profile: for each intent, which control to set to what. Controls are found on the inverter's own
entities by pattern (select.*work_mode_priority …), so one profile fits every installation of that integration.
A brand that isn't built in gets a profile the user makes in the panel: pick the control and value for each intent.

Values may use {min_soc}, {soc}, {target}, {rate} (% of max power), {power_w} and {current}.
"""

from __future__ import annotations

import re
from typing import Any

# step: (pattern on the entity id, service, value). Service: "select" | "number" | "on" | "off" | "press" | "<domain>.<service>"
PROFILES: dict[str, dict[str, Any]] = {
    "growatt": {
        "name": "Growatt (SPH/SPA, lokal styring)",
        "match": r"growatt",
        "normal": [(r"select\..*work_mode_priority$", "select", "Load first"), (r"number\..*load_first_stop_discharge$", "number", "{min_soc}"),
                   (r"select\..*battery_first_grid_charge$", "select", "Disabled")],
        "hold": [(r"select\..*work_mode_priority$", "select", "Load first"), (r"number\..*load_first_stop_discharge$", "number", "{soc}"),
                 (r"select\..*battery_first_grid_charge$", "select", "Disabled")],
        "charge": [(r"switch\..*battery_first_slot_1_enabled$", "on", None), (r"select\..*battery_first_slot_1_start$", "select", "00:00"),
                   (r"select\..*battery_first_slot_1_end$", "select", "23:59"), (r"number\..*battery_first_charge_rate$", "number", "{rate}"),
                   (r"number\..*battery_first_stop_charge$", "number", "{target}"), (r"select\..*battery_first_grid_charge$", "select", "Enabled"),
                   (r"select\..*work_mode_priority$", "select", "Battery first")],
    },
    "huawei_solar": {
        "name": "Huawei SUN2000 / LUNA2000",
        "match": r"huawei|sun2000|luna",
        "normal": [(r"select\..*storage_working_mode.*$", "select", "Maximise Self Consumption"),
                   (r"number\..*maximum_discharging_power$", "number", "{max_power_w}")],
        "hold": [(r"select\..*storage_working_mode.*$", "select", "Maximise Self Consumption"),
                 (r"number\..*maximum_discharging_power$", "number", "0")],
        "charge": [(r"number\..*maximum_discharging_power$", "number", "{max_power_w}"),
                   ("huawei_solar.forcible_charge_soc", "service", {"target_soc": "{target}", "power": "{power_w}"})],
    },
    "solax_modbus": {
        "name": "SolaX (Modbus)",
        "match": r"solax",
        "normal": [(r"select\..*charger_use_mode$", "select", "Self Use Mode")],
        "hold": [(r"select\..*charger_use_mode$", "select", "Manual Mode"), (r"select\..*manual_mode_select$", "select", "Stop Charge and Discharge")],
        "charge": [(r"select\..*charger_use_mode$", "select", "Manual Mode"), (r"select\..*manual_mode_select$", "select", "Force Charge")],
    },
    "sungrow": {
        "name": "Sungrow (Modbus)",
        "match": r"sungrow|sh\d+rt",
        "normal": [(r"select\..*ems_mode.*$", "select", "Self-consumption mode (default)")],
        "hold": [(r"select\..*ems_mode.*$", "select", "Forced mode"), (r"select\..*battery_forced_charge_discharge.*$", "select", "Stop (default)")],
        "charge": [(r"select\..*ems_mode.*$", "select", "Forced mode"), (r"number\..*forced_charge_discharge_power.*$", "number", "{power_w}"),
                   (r"select\..*battery_forced_charge_discharge.*$", "select", "Forced charge")],
    },
    "solaredge_modbus_multi": {
        "name": "SolarEdge (Modbus Multi)",
        "match": r"solaredge",
        "normal": [(r"select\..*storage_control_mode$", "select", "Maximize Self Consumption")],
        "hold": [(r"select\..*storage_control_mode$", "select", "Remote Control"), (r"select\..*storage_command_mode$", "select", "Solar Power Only (Off)")],
        "charge": [(r"select\..*storage_control_mode$", "select", "Remote Control"), (r"number\..*storage_charge_limit$", "number", "{power_w}"),
                   (r"select\..*storage_command_mode$", "select", "Charge from Solar Power and Grid")],
    },
    "foxess_modbus": {
        "name": "Fox ESS (Modbus)",
        "match": r"foxess|fox_",
        "normal": [(r"select\..*work_mode$", "select", "Self Use")],
        "hold": [(r"select\..*work_mode$", "select", "Back-up")],
        "charge": [(r"select\..*work_mode$", "select", "Force Charge")],
    },
    "givenergy_local": {
        "name": "GivEnergy",
        "match": r"givenergy|givtcp",
        "normal": [(r"switch\..*enable_charge$", "off", None), (r"number\..*battery_discharge_limit$", "number", "{rate}")],
        "hold": [(r"switch\..*enable_charge$", "off", None), (r"number\..*battery_discharge_limit$", "number", "0")],
        "charge": [(r"number\..*charge_target_soc$", "number", "{target}"), (r"number\..*battery_charge_limit$", "number", "{rate}"),
                   (r"switch\..*enable_charge$", "on", None)],
    },
}

# Chargers: almost every integration has a switch to start/stop and a number for the current.
CHARGER_SWITCH = r"switch\..*(charg|enable|is_enabled|charge_control|charging_allowed|start_stop|pause|resume)"
CHARGER_CURRENT = r"number\..*(current|ampere|amp|charging_limit|dynamic_limit)"
CHARGER_SERVICES = {
    "keba": {"charge": [("keba.set_current", "service", {"current": "{current}"}), ("keba.enable", "service", {})],
             "stop": [("keba.disable", "service", {})]},
}


def fill(value: Any, ctx: dict[str, Any]) -> Any:
    if isinstance(value, str) and "{" in value:
        out = value.format(**{k: (round(v) if isinstance(v, float) else v) for k, v in ctx.items()})
        try:
            return float(out) if "." in out else int(out)
        except ValueError:
            return out
    if isinstance(value, dict):
        return {k: fill(v, ctx) for k, v in value.items()}
    return value


def resolve(steps: list, entities: list[str], ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """The service calls a list of steps means for these entities (steps whose control isn't there are left out)."""
    calls = []
    for pattern, kind, value in steps:
        if kind == "service":
            domain, service = pattern.split(".", 1)
            calls.append({"domain": domain, "service": service, "data": fill(value, ctx)})
            continue
        if "." in pattern and not any(c in pattern for c in "\\*^$[(+"):
            entity = pattern if pattern in entities else None  # an exact entity (custom profiles)
        else:
            entity = next((e for e in entities if re.search(pattern, e)), None)
        if entity is None:
            continue
        domain = entity.split(".")[0]
        if kind == "select":
            calls.append({"domain": domain, "service": "select_option", "data": {"entity_id": entity, "option": fill(value, ctx)}})
        elif kind == "number":
            calls.append({"domain": domain, "service": "set_value", "data": {"entity_id": entity, "value": fill(value, ctx)}})
        elif kind in ("on", "off"):
            calls.append({"domain": domain, "service": f"turn_{kind}", "data": {"entity_id": entity}})
        elif kind == "press":
            calls.append({"domain": domain, "service": "press", "data": {"entity_id": entity}})
    return calls


def guess_profile(entities: list[str], platforms: set[str]) -> str | None:
    """The built-in profile for the inverter in this home, from its integration or its entity names."""
    for key, p in PROFILES.items():
        if key in platforms:
            return key
    for key, p in PROFILES.items():
        hits = [s for steps in (p["normal"], p["hold"], p["charge"]) for s in steps if s[1] != "service"]
        if any(re.search(p["match"], e) for e in entities) and \
                sum(1 for pat, _k, _v in hits if any(re.search(pat, e) for e in entities)) >= max(1, len(hits) // 2):
            return key
    return None


def charger_calls(intent: str, entities: list[str], platform: str | None, current: float) -> list[dict[str, Any]]:
    """Start at a current, or stop - by the charger's own services where known, else its switch and number."""
    ctx = {"current": round(current)}
    if platform in CHARGER_SERVICES:
        return resolve(CHARGER_SERVICES[platform][intent], entities, ctx)
    switch = next((e for e in entities if re.search(CHARGER_SWITCH, e)), None)
    number = next((e for e in entities if re.search(CHARGER_CURRENT, e)), None)
    calls = []
    paused = switch is not None and re.search(r"pause", switch)
    if intent == "charge":
        if number:
            calls.append({"domain": "number", "service": "set_value", "data": {"entity_id": number, "value": round(current)}})
        if switch:
            calls.append({"domain": "switch", "service": "turn_off" if paused else "turn_on", "data": {"entity_id": switch}})
    elif switch:
        calls.append({"domain": "switch", "service": "turn_on" if paused else "turn_off", "data": {"entity_id": switch}})
    return calls

"""Telling an inverter and a charger what to do - the same few intents for every brand.

Battery intents:
- "normal": the house first; the battery covers the house and stores solar surplus (self-use)
- "hold": keep what is in the battery (no discharging); solar may still fill it
- "charge": charge from the grid now, at a power, up to a target level

Charger intents: "charge" at a current (A), or "stop".

Each brand is a profile: for each intent, which control to set to what. Controls are found on the inverter's own
entities by pattern (select.*work_mode_priority …), so one profile fits every installation of that integration.
A brand that isn't built in gets a profile the user makes in the panel: pick the control and value for each intent.

Values may use {min_soc}, {soc}, {target}, {rate} (% of max power), {power_w}, {current} and {house_w} (the house's
use now - for a micro-inverter that is told how many watts to give, like EcoFlow PowerStream).

Models: one integration can cover inverter models that are controlled differently (Growatt SPH/SPA work with
"battery first" time slots, MIN/MOD TL-XH with a priority mode). A profile can name the models it is for ("models",
matched on the device's model in Home Assistant), and the profile for the model found is chosen.

Safety: every control a profile names is required, unless it is listed under "optional". If one is missing for an
intent, the engine won't control at all and says what is missing - never half a command.
"""

from __future__ import annotations

import re
from typing import Any

# step: (pattern on the entity id, service, value). Service: "select" | "number" | "on" | "off" | "press" | "<domain>.<service>"
PROFILES: dict[str, dict[str, Any]] = {
    "growatt": {
        "name": "Growatt (SPH/SPA)",
        "match": r"growatt",
        "models": r"SPH|SPA",
        "tested": True,
        "normal": [(r"select\..*work_mode_priority$", "select", "Load first"), (r"number\..*load_first_stop_discharge$", "number", "{min_soc}"),
                   (r"select\..*battery_first_grid_charge$", "select", "Disabled")],
        "hold": [(r"select\..*work_mode_priority$", "select", "Load first"), (r"number\..*load_first_stop_discharge$", "number", "{soc}"),
                 (r"select\..*battery_first_grid_charge$", "select", "Disabled")],
        "charge": [(r"switch\..*battery_first_slot_1_enabled$", "on", None), (r"select\..*battery_first_slot_1_start$", "select", "00:00"),
                   (r"select\..*battery_first_slot_1_end$", "select", "23:59"), (r"number\..*battery_first_charge_rate$", "number", "{rate}"),
                   (r"number\..*battery_first_stop_charge$", "number", "{target}"), (r"select\..*battery_first_grid_charge$", "select", "Enabled"),
                   (r"select\..*work_mode_priority$", "select", "Battery first")],
    },
    "growatt_tlxh": {
        "name": "Growatt (MIN/MOD TL-XH)",
        "match": r"growatt",
        "models": r"TL-?XH|\bMIN\b|\bMOD\b|\bMID\b",
        "normal": [(r"select\..*(work_mode_priority|priority_mode|inverter_priority)$", "select", "Load first"),
                   (r"number\..*(load_first_stop_discharge|discharge_stop_soc)$", "number", "{min_soc}"),
                   (r"(select|switch)\..*(ac_charge|grid_charge).*$", "off", None)],
        "hold": [(r"select\..*(work_mode_priority|priority_mode|inverter_priority)$", "select", "Load first"),
                 (r"number\..*(load_first_stop_discharge|discharge_stop_soc)$", "number", "{soc}"),
                 (r"(select|switch)\..*(ac_charge|grid_charge).*$", "off", None)],
        "charge": [(r"number\..*(battery_first_stop_charge|charge_stop_soc)$", "number", "{target}"),
                   (r"number\..*(battery_first_charge_rate|charge_power_rate)$", "number", "{rate}"),
                   (r"(select|switch)\..*(ac_charge|grid_charge).*$", "on", None),
                   (r"select\..*(work_mode_priority|priority_mode|inverter_priority)$", "select", "Battery first")],
        "optional": [r"number\..*(battery_first_charge_rate|charge_power_rate)$"],
    },
    # Deye hybrid (also Sunsynk-built) via the Solarman integration (davidrapan/ha-solarman). Deye works with six
    # "Time of Use" programmes; each has a battery level it won't go below and whether it may charge from the grid.
    # All six are set alike, so whichever programme is running does what the plan wants - no clock times are touched.
    "solarman": {
        "name": "Deye (Solarman)",
        "match": r"deye|solarman",
        "models": r"deye|SUN-\d+K-SG|sg0\dlp|sg0\dhp",
        "normal": [(r"select\..*time_of_use$", "select", "Week"), (r"switch\..*battery_grid_charging$", "off", None)]
        + [(rf"number\..*program_{n}_soc$", "number", "{min_soc}") for n in range(1, 7)]
        + [(rf"select\..*program_{n}_charging$", "select", "Disabled") for n in range(1, 7)],
        "hold": [(r"select\..*time_of_use$", "select", "Week"), (r"switch\..*battery_grid_charging$", "off", None)]
        + [(rf"number\..*program_{n}_soc$", "number", "{soc}") for n in range(1, 7)]
        + [(rf"select\..*program_{n}_charging$", "select", "Disabled") for n in range(1, 7)],
        "charge": [(r"select\..*time_of_use$", "select", "Week"), (r"switch\..*battery_grid_charging$", "on", None)]
        + [(rf"number\..*program_{n}_soc$", "number", "{target}") for n in range(1, 7)]
        + [(rf"select\..*program_{n}_charging$", "select", "Grid") for n in range(1, 7)],
    },
    # Deye via ESPHome and local Modbus (klatremis/esphome-for-deye): the six "Time point" programmes, set alike.
    "deye_esphome": {
        "name": "Deye (ESPHome, local Modbus)",
        "match": r"deye|time_point_\d",
        "models": r"esphome|SG04LP3",
        "normal": [(r"switch\..*time_of_use$", "on", None), (r"switch\..*grid_charge$", "off", None)]
        + [(rf"number\..*time_point_{n}_capacity$", "number", "{min_soc}") for n in range(1, 7)]
        + [(rf"switch\..*time_point_{n}_charge_enable$", "off", None) for n in range(1, 7)],
        "hold": [(r"switch\..*time_of_use$", "on", None), (r"switch\..*grid_charge$", "off", None)]
        + [(rf"number\..*time_point_{n}_capacity$", "number", "{soc}") for n in range(1, 7)]
        + [(rf"switch\..*time_point_{n}_charge_enable$", "off", None) for n in range(1, 7)],
        "charge": [(r"switch\..*time_of_use$", "on", None), (r"switch\..*grid_charge$", "on", None)]
        + [(rf"number\..*time_point_{n}_capacity$", "number", "{target}") for n in range(1, 7)]
        + [(rf"switch\..*time_point_{n}_charge_enable$", "on", None) for n in range(1, 7)],
    },
    # Sofar hybrid (HYD, ESI …) via Solarman (sofar_g3hyd definition). Normal is "Self Use"; hold and charge use
    # "Passive", where the battery's power is kept between a minimum and a maximum (positive = charging):
    # hold = 0 … max (no discharging, the sun may still fill it), charge = exactly the planned power.
    "sofar": {
        "name": "Sofar (Solarman)",
        "match": r"sofar|storage_control_mode",
        "models": r"sofar|\bHYD\b|\bESI\b",
        "normal": [(r"select\..*storage_control_mode$", "select", "Self Use")],
        "hold": [(r"number\..*passive_minimum_battery_power$", "number", "0"),
                 (r"number\..*passive_maximum_battery_power$", "number", "{max_charge_w}"),
                 (r"select\..*storage_control_mode$", "select", "Passive")],
        "charge": [(r"number\..*passive_maximum_battery_power$", "number", "{power_w}"),
                   (r"number\..*passive_minimum_battery_power$", "number", "{power_w}"),
                   (r"select\..*storage_control_mode$", "select", "Passive")],
        # Selling from the battery (only when the user turns it on): checked in the integration's source.
        "export": [(r"number\..*passive_minimum_battery_power$", "number", "-{power_w}"),
                   (r"number\..*passive_maximum_battery_power$", "number", "-{power_w}"),
                   (r"select\..*storage_control_mode$", "select", "Passive")],
    },
    # Sigenergy (TypQxQ/Sigenergy-Local-Modbus): Remote EMS on, then its control mode; limits in kW.
    "sigen": {
        "name": "Sigenergy (local Modbus)",
        "optional": [r"number\..*ess_max_discharging_limit$"],
        "match": r"sigen",
        "source": "integration",
        "normal": [(r"number\..*ess_max_discharging_limit$", "number", "{max_power_kw}"), (r"switch\..*remote_ems.*$", "on", None), (r"select\..*remote_ems_control_mode$", "select", "Maximum Self Consumption")],
        "hold": [(r"switch\..*remote_ems.*$", "on", None), (r"select\..*remote_ems_control_mode$", "select", "Command Charging (PV First)"),
                 (r"number\..*ess_max_charging_limit$", "number", "{max_charge_kw}")],
        "charge": [(r"switch\..*remote_ems.*$", "on", None), (r"number\..*ess_max_charging_limit$", "number", "{power_kw}"),
                   (r"select\..*remote_ems_control_mode$", "select", "Command Charging (Grid First)")],
        # Selling from the battery (only when the user turns it on): checked in the integration's source.
        "export": [(r"switch\..*remote_ems.*$", "on", None),
                   (r"number\..*ess_max_discharging_limit$", "number", "{power_kw}"),
                   (r"select\..*remote_ems_control_mode$", "select", "Command Discharging (ESS First)")],
    },
    # Sofar via SolaX Modbus (wills106): "Energy Storage Mode" and its passive mode battery power min/max.
    "sofar_solax": {
        "name": "Sofar (SolaX Modbus)",
        "match": r"sofar|energy_storage_mode",
        "source": "integration",
        "normal": [(r"select\..*energy_storage_mode$", "select", "Self Use")],
        "hold": [(r"number\..*passive_mode_battery_power_min$", "number", "0"),
                 (r"number\..*passive_mode_battery_power_max$", "number", "{max_charge_w}"),
                 (r"select\..*energy_storage_mode$", "select", "Passive Mode")],
        "charge": [(r"number\..*passive_mode_battery_power_max$", "number", "{power_w}"),
                   (r"number\..*passive_mode_battery_power_min$", "number", "{power_w}"),
                   (r"select\..*energy_storage_mode$", "select", "Passive Mode")],
        # Selling from the battery (only when the user turns it on): checked in the integration's source.
        "export": [(r"number\..*passive_mode_battery_power_min$", "number", "-{power_w}"),
                   (r"number\..*passive_mode_battery_power_max$", "number", "-{power_w}"),
                   (r"select\..*energy_storage_mode$", "select", "Passive Mode")],
    },
    # Tesla Powerwall (Teslemetry / Tesla Fleet): charging is done by raising the backup reserve with grid charging
    # allowed; hold keeps the reserve at today's level.
    "tesla": {
        "name": "Tesla Powerwall (Teslemetry / Fleet)",
        "match": r"powerwall|backup_reserve",
        "source": "integration",
        "normal": [(r"switch\..*(allow_charging_from_grid|grid_charging)$", "off", None), (r"number\..*backup_reserve$", "number", "{min_soc}"),
                   (r"select\..*operation_mode$", "select", "self_consumption")],
        "hold": [(r"number\..*backup_reserve$", "number", "{soc}"), (r"select\..*operation_mode$", "select", "self_consumption")],
        "charge": [(r"switch\..*(allow_charging_from_grid|grid_charging)$", "on", None), (r"number\..*backup_reserve$", "number", "{target}"),
                   (r"select\..*operation_mode$", "select", "self_consumption")],
        "optional": [r"select\..*operation_mode$"],
    },
    # Enphase IQ Battery (Envoy, built-in integration): storage mode, reserve level and "Charge from grid".
    "enphase_envoy": {
        "name": "Enphase IQ Battery (Envoy)",
        "match": r"enpower|enphase|envoy",
        "source": "integration",
        "normal": [(r"switch\..*charge_from_grid$", "off", None), (r"number\..*reserve.*(level|soc)$", "number", "{min_soc}"),
                   (r"select\..*storage_mode$", "select", "self_consumption")],
        "hold": [(r"number\..*reserve.*(level|soc)$", "number", "{soc}"), (r"select\..*storage_mode$", "select", "self_consumption")],
        "charge": [(r"switch\..*charge_from_grid$", "on", None), (r"number\..*reserve.*(level|soc)$", "number", "{target}"),
                   (r"select\..*storage_mode$", "select", "self_consumption")],
        "optional": [r"select\..*storage_mode$"],
    },
    # Victron ESS (GX via Modbus). The grid setpoint is left alone, so the owner's own setting stays.
    "victron": {
        "name": "Victron (ESS)",
        "match": r"victron|\bess_",
        "models": r"victron|multiplus|quattro|cerbo|venus",
        "normal": [(r"switch\..*ess_force_charge$", "off", None),
                   (r"number\..*ess_maximum_discharge_power$", "number", "{max_power_w}")],
        "hold": [(r"switch\..*ess_force_charge$", "off", None),
                 (r"number\..*ess_maximum_discharge_power$", "number", "0")],
        "charge": [(r"number\..*ess_maximum_charge_power$", "number", "{power_w}"),
                   (r"switch\..*ess_force_charge$", "on", None)],
    },
    # EcoFlow PowerStream (EcoFlow Cloud integration): a micro-inverter that gives the house the watts it is told
    # ("custom load"), from a Delta/River power station. It can't charge from the grid - that's the station's own AC
    # charging - so the plan never buys for the battery with this profile.
    "ecoflow": {
        "name": "EcoFlow PowerStream",
        "match": r"powerstream|ecoflow",
        "models": r"powerstream|ecoflow",
        "grid_charge": False,
        "normal": [(r"number\..*custom_load_power.*$", "number", "{house_w}"),
                   (r"number\..*min_discharge_level$", "number", "{min_soc}")],
        "hold": [(r"number\..*custom_load_power.*$", "number", "0"),
                 (r"number\..*min_discharge_level$", "number", "{soc}")],
        "charge": [(r"number\..*custom_load_power.*$", "number", "0"),
                   (r"number\..*max_charge_level$", "number", "{target}")],
    },
    # Huawei (wlcrs/huawei_solar): "Working Mode" ("Maximise self consumption"), maximum discharging power, and the
    # forcible_charge_soc service (needs the battery's device_id); "Stop forcible charge" ends a charge.
    "huawei_solar": {
        "name": "Huawei SUN2000 / LUNA2000",
        "match": r"huawei|sun2000|luna|batteries_",
        "source": "integration",
        "normal": [(r"button\..*stop_forcible_charge$", "press", None),
                   (r"select\..*(?<!emma_)working_mode(_settings)?$", "select", "Maximise self consumption"),
                   (r"number\..*maximum_discharging_power$", "number", "{max_power_w}")],
        "hold": [(r"button\..*stop_forcible_charge$", "press", None),
                 (r"select\..*(?<!emma_)working_mode(_settings)?$", "select", "Maximise self consumption"),
                 (r"number\..*maximum_discharging_power$", "number", "0")],
        "charge": [(r"number\..*maximum_discharging_power$", "number", "{max_power_w}"),
                   ("huawei_solar.forcible_charge_soc", "service", {"device_id": "{device_id}", "target_soc": "{target}", "power": "{power_w}"})],
        # Selling from the battery (only when the user turns it on): checked in the integration's source.
        "export": [(r"number\..*maximum_discharging_power$", "number", "{max_power_w}"),
                   ("huawei_solar.forcible_discharge_soc", "service", {"device_id": "{device_id}", "target_soc": "{target}", "power": "{power_w}"})],
        "optional": [r"select\..*(?<!emma_)working_mode(_settings)?$", r"button\..*stop_forcible_charge$"],
    },
    "solax_modbus": {
        "name": "SolaX (Modbus)",
        "match": r"solax",
        "normal": [(r"select\..*charger_use_mode$", "select", "Self Use Mode")],
        "hold": [(r"select\..*charger_use_mode$", "select", "Manual Mode"), (r"select\..*manual_mode_select$", "select", "Stop Charge and Discharge")],
        "charge": [(r"select\..*charger_use_mode$", "select", "Manual Mode"), (r"select\..*manual_mode_select$", "select", "Force Charge")],
        # Selling from the battery (only when the user turns it on): checked in the integration's source.
        "export": [(r"select\..*charger_use_mode$", "select", "Manual Mode"),
                   (r"select\..*manual_mode_select$", "select", "Force Discharge")],
    },
    "sungrow": {
        "name": "Sungrow (Modbus)",
        "match": r"sungrow|sh\d+rt",
        "normal": [(r"select\..*ems_mode.*$", "select", "Self-consumption mode (default)")],
        "hold": [(r"select\..*ems_mode.*$", "select", "Forced mode"), (r"select\..*battery_forced_charge_discharge.*$", "select", "Stop (default)")],
        "charge": [(r"select\..*ems_mode.*$", "select", "Forced mode"), (r"number\..*forced_charge_discharge_power.*$", "number", "{power_w}"),
                   (r"select\..*battery_forced_charge_discharge.*$", "select", "Forced charge")],
        # Selling from the battery (only when the user turns it on): checked in the integration's source.
        "export": [(r"select\..*ems_mode.*$", "select", "Forced mode"),
                   (r"number\..*forced_charge_discharge_power.*$", "number", "{power_w}"),
                   (r"select\..*battery_forced_charge_discharge.*$", "select", "Forced discharge")],
    },
    "solaredge_modbus_multi": {
        "name": "SolarEdge (Modbus Multi)",
        "match": r"solaredge",
        "normal": [(r"select\..*storage_control_mode$", "select", "Maximize Self Consumption")],
        "source": "integration",
        "hold": [(r"select\..*storage_control_mode$", "select", "Remote Control"), (r"number\..*storage_command_timeout$", "number", "3600"),
                 (r"select\..*storage_command_mode$", "select", "Charge from Solar Power")],
        "charge": [(r"select\..*ac_charge_policy$", "select", "Always Allowed"), (r"select\..*storage_control_mode$", "select", "Remote Control"),
                   (r"number\..*storage_command_timeout$", "number", "3600"), (r"number\..*storage_charge_limit$", "number", "{power_w}"),
                   (r"select\..*storage_command_mode$", "select", "Charge from Solar Power and Grid")],
        # Selling from the battery (only when the user turns it on): checked in the integration's source.
        "export": [(r"select\..*storage_control_mode$", "select", "Remote Control"),
                   (r"number\..*storage_command_timeout$", "number", "3600"),
                   (r"number\..*storage_discharge_limit$", "number", "{power_w}"),
                   (r"select\..*storage_command_mode$", "select", "Discharge to Maximize Export")],
        "optional": [r"number\..*storage_command_timeout$", r"select\..*ac_charge_policy$"],
    },
    "foxess_modbus": {
        "name": "Fox ESS (Modbus)",
        "match": r"foxess|fox_",
        "normal": [(r"select\..*work_mode$", "select", "Self Use")],
        "hold": [(r"select\..*work_mode$", "select", "Back-up")],
        "charge": [(r"number\..*force_charge_power$", "number", "{power_w}"), (r"number\..*force_charge_max_soc$", "number", "{target}"),
                   (r"select\..*work_mode$", "select", "Force Charge")],
        # Selling from the battery (only when the user turns it on): checked in the integration's source.
        "export": [(r"number\..*force_discharge_power$", "number", "{power_w}"),
                   (r"select\..*work_mode$", "select", "Force Discharge")],
        "optional": [r"number\..*force_charge_power$", r"number\..*force_charge_max_soc$"],
        "source": "integration",
    },
    # GivEnergy (cdpuk/givenergy-local): charging is a "timed charge" (service, needs the inverter's device_id) with
    # a charge target; hold pauses discharging.
    "givenergy_local": {
        "name": "GivEnergy (GivEnergy Local)",
        "match": r"givenergy|givtcp",
        "source": "integration",
        "normal": [("givenergy_local.activate_mode_eco", "service", {"device_id": "{device_id}"}), ("givenergy_local.disable_timed_charge", "service", {"device_id": "{device_id}"}),
                   (r"select\..*battery_pause_mode$", "select", "Not Paused")],
        "hold": [("givenergy_local.activate_mode_eco", "service", {"device_id": "{device_id}"}), ("givenergy_local.disable_timed_charge", "service", {"device_id": "{device_id}"}),
                 (r"select\..*battery_pause_mode$", "select", "Pause Discharge")],
        "charge": [(r"select\..*battery_pause_mode$", "select", "Not Paused"),
                   (r"number\..*battery_charge_power_limit$", "number", "{power_w}"),
                   ("givenergy_local.enable_timed_charge", "service",
                    {"device_id": "{device_id}", "start_time": "00:00", "end_time": "23:59", "charge_target": "{target}"})],
        # Selling from the battery (only when the user turns it on): checked in the integration's source.
        "export": [(r"select\..*battery_pause_mode$", "select", "Not Paused"),
                   ("givenergy_local.activate_mode_timed_export", "service", {"device_id": "{device_id}", "start_time": "00:00", "end_time": "23:59"})],
        "optional": [r"number\..*battery_charge_power_limit$"],
    },
    # Solis (Pho3niX90/solis_modbus): remote-control force charge with its power and timeout (1-30 min, so it is
    # re-sent every 10 minutes); hold is a force charge at 0 W, which stops discharging.
    "solis_modbus": {
        "name": "Solis (Solis Modbus)",
        "match": r"solis",
        "source": "integration",
        "reassert_s": 600,
        "normal": [(r"select\..*rc_force_charge_discharge$", "select", "None")],
        "hold": [(r"select\..*rc_force_charge_discharge$", "select", "Solis RC Force Battery Charge"),
                 (r"number\..*rc_force_battery_charge_power$", "number", "0"), (r"number\..*rc_timeout$", "number", "30")],
        "charge": [(r"select\..*rc_force_charge_discharge$", "select", "Solis RC Force Battery Charge"),
                   (r"number\..*rc_force_battery_charge_power$", "number", "{power_w}"), (r"number\..*rc_timeout$", "number", "30")],
        # Selling from the battery (only when the user turns it on): checked in the integration's source.
        "export": [(r"select\..*rc_force_charge_discharge$", "select", "Solis RC Force Battery Discharge"),
                   (r"number\..*rc_force_battery_discharge_power$", "number", "{power_w}"),
                   (r"number\..*rc_timeout$", "number", "30")],
    },
    # Alpha ESS (Poshy163/homeassistant-alphaESS, cloud): charge and discharge windows by service, with the serial.
    "alphaess": {
        "name": "Alpha ESS (cloud)",
        "match": r"alpha_?ess",
        "source": "integration",
        "normal": [("alphaess.setbatterycharge", "service", {"serial": "{serial}", "enabled": False, "cp1start": "00:00", "cp1end": "00:00",
                                                             "cp2start": "00:00", "cp2end": "00:00", "chargestopsoc": 100}),
                   ("alphaess.setbatterydischarge", "service", {"serial": "{serial}", "enabled": False, "dp1start": "00:00", "dp1end": "00:00",
                                                                "dp2start": "00:00", "dp2end": "00:00", "dischargecutoffsoc": "{min_soc}"})],
        "hold": [("alphaess.setbatterydischarge", "service", {"serial": "{serial}", "enabled": True, "dp1start": "00:00", "dp1end": "23:59",
                                                              "dp2start": "00:00", "dp2end": "00:00", "dischargecutoffsoc": "{soc}"})],
        "charge": [("alphaess.setbatterycharge", "service", {"serial": "{serial}", "enabled": True, "cp1start": "00:00", "cp1end": "23:59",
                                                             "cp2start": "00:00", "cp2end": "00:00", "chargestopsoc": "{target}"})],
    },
}

# Chargers: almost every integration has a switch to start/stop and a number for the current.
CHARGER_SWITCH = r"switch\..*(charg|enable|is_enabled|charge_control|charging_allowed|start_stop|pause|resume)"
CHARGER_CURRENT = r"number\..*(current|ampere|amp|charging_limit|dynamic_limit)"
# Chargers by integration - from each integration's own source code. The current is in amps; {device_id} is the
# charger's device in Home Assistant. Not on the list: the generic switch + number above.
CHARGER_SERVICES = {
    "keba": {"charge": [("keba.set_current", "service", {"current": "{current}"}), ("keba.enable", "service", {})],
             "stop": [("keba.disable", "service", {})]},
    # Easee (nordicopen/easee_hass): actions with the charger's device
    "easee": {"charge": [("easee.set_charger_dynamic_limit", "service", {"device_id": "{device_id}", "current": "{current}"}),
                         ("easee.action_command", "service", {"device_id": "{device_id}", "action_command": "resume"})],
              "stop": [("easee.action_command", "service", {"device_id": "{device_id}", "action_command": "pause"})]},
    # Zaptec (custom-components/zaptec): "Available current" and the Resume/Stop charging buttons
    "zaptec": {"charge": [(r"number\..*available_current$", "number", "{current}"), (r"button\..*resume_charging$", "press", None)],
               "stop": [(r"button\..*stop_charging$", "press", None)]},
    # go-e (marq24/ha-goecharger-api2): "Requested current" and "Force state" (2 = charge, 1 = don't charge)
    "goecharger_api2": {"charge": [(r"number\..*_amp$", "number", "{current}"), (r"select\..*_frc$", "select", "2")],
                        "stop": [(r"select\..*_frc$", "select", "1")]},
    # Wallbox (built in): "Maximum charging current" and "Pause/resume" (on = charging)
    "wallbox": {"charge": [(r"number\..*maximum_charging_current$", "number", "{current}"), (r"switch\..*pause_resume$", "on", None)],
                "stop": [(r"switch\..*pause_resume$", "off", None)]},
    # Peblar (built in): "Charge limit" and "Charge"
    "peblar": {"charge": [(r"number\..*charge_limit$", "number", "{current}"), (r"switch\..*_charge$", "on", None)],
               "stop": [(r"switch\..*_charge$", "off", None)]},
    # OCPP (lbbrhzn/ocpp): "Maximum Current" and "Charge Control"
    "ocpp": {"charge": [(r"number\..*maximum_current$", "number", "{current}"), (r"switch\..*charge_control$", "on", None)],
             "stop": [(r"switch\..*charge_control$", "off", None)]},
    # Alfen (leeyuentuen/alfen_wallbox): the socket's max current; 0 A pauses
    "alfen_wallbox": {"charge": [(r"number\..*power_connector_max_current_socket_1$", "number", "{current}")],
                      "stop": [(r"number\..*power_connector_max_current_socket_1$", "number", "0")]},
    # Ohme (built in): no current control - "Charge mode" max charge / paused
    "ohme": {"charge": [(r"select\..*charge_mode$", "select", "max_charge")], "stop": [(r"select\..*charge_mode$", "select", "paused")]},
    # myenergi zappi (CJNE/ha-myenergi): "Charge Mode" Fast / Stopped (no current control)
    "myenergi": {"charge": [(r"select\..*charge_mode$", "select", "Fast")], "stop": [(r"select\..*charge_mode$", "select", "Stopped")]},
}


def fill(value: Any, ctx: dict[str, Any]) -> Any:
    if isinstance(value, str) and re.fullmatch(r"-?\d+(?:\.\d+)?", value):
        return float(value) if "." in value else int(value)  # a plain number in a profile ("0")
    if isinstance(value, str) and "{" in value:
        out = value.format(**{k: (round(v, 2) if isinstance(v, float) else v) for k, v in ctx.items()})
        try:
            return float(out) if "." in out else int(out)
        except ValueError:
            return out
    if isinstance(value, dict):
        return {k: fill(v, ctx) for k, v in value.items()}
    return value


def _find(pattern: str, entities: list[str]) -> str | None:
    if "." in pattern and not any(c in pattern for c in "\\*^$[(+"):
        return pattern if pattern in entities else None  # an exact entity (custom profiles)
    return next((e for e in entities if re.search(pattern, e)), None)


def check(steps: dict[str, list], entities: list[str], optional: list[str] | None = None,
          services: set[str] | None = None) -> dict[str, dict[str, Any]]:
    """For each intent: the controls found, and the required ones that are missing."""
    out = {}
    for intent, items in steps.items():
        found, missing = [], []
        for pattern, kind, _value in items:
            if kind == "service":
                ok = services is None or pattern in services
                (found if ok else missing).append({"control": pattern, "entity": pattern if ok else None, "optional": False})
                continue
            entity = _find(pattern, entities)
            opt = pattern in (optional or [])
            row = {"control": pattern, "entity": entity, "optional": opt}
            (found if entity or opt else missing).append(row)
        out[intent] = {"found": found, "missing": missing}
    return out


def missing(result: dict[str, dict[str, Any]]) -> list[str]:
    """Required controls that are missing. Selling is extra: without its controls the battery is still controlled,
    it just doesn't sell."""
    return [m["control"] for intent, r in result.items() if intent != "export" for m in r["missing"]]


def resolve(steps: list, entities: list[str], ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """The service calls a list of steps means for these entities (steps whose control isn't there are left out)."""
    calls = []
    for pattern, kind, value in steps:
        if kind == "service":
            domain, service = pattern.split(".", 1)
            calls.append({"domain": domain, "service": service, "data": fill(value, ctx)})
            continue
        entity = _find(pattern, entities)
        if entity is None:
            continue
        domain = entity.split(".")[0]
        if kind == "select":
            calls.append({"domain": domain, "service": "select_option", "data": {"entity_id": entity, "option": str(fill(value, ctx))}})
        elif kind == "number":
            calls.append({"domain": domain, "service": "set_value", "data": {"entity_id": entity, "value": fill(value, ctx)}})
        elif kind in ("on", "off") and domain == "select":
            calls.append({"domain": domain, "service": "select_option", "data": {"entity_id": entity, "option": "Enabled" if kind == "on" else "Disabled"}})
        elif kind in ("on", "off"):
            calls.append({"domain": domain, "service": f"turn_{kind}", "data": {"entity_id": entity}})
        elif kind == "press":
            calls.append({"domain": domain, "service": "press", "data": {"entity_id": entity}})
    return calls


def guess_profile(entities: list[str], platforms: set[str], model: str | None = None) -> str | None:
    """The built-in profile for the inverter in this home: its model first, then its integration or entity names."""
    if model:
        for key, p in PROFILES.items():
            if p.get("models") and re.search(p["models"], model, re.I) and \
                    (any(re.search(p["match"], e) for e in entities) or key.split("_")[0] in platforms or any(key.startswith(x) for x in platforms if x)):
                return key
    def fits(p: dict) -> bool:
        hits = [s for steps in (p["normal"], p["hold"], p["charge"]) for s in steps if s[1] != "service"]
        if not hits:
            return True  # all by services (Alpha ESS): the integration's name is all there is
        return sum(1 for pat, _k, _v in hits if any(re.search(pat, e) for e in entities)) >= max(1, len(hits) // 2)

    for key, p in PROFILES.items():
        # The integration's name only counts when its controls are there too: Solarman serves Deye and Sofar alike.
        if key in platforms and fits(p):
            return key
    for key, p in PROFILES.items():
        hits = [s for steps in (p["normal"], p["hold"], p["charge"]) for s in steps if s[1] != "service"]
        if any(re.search(p["match"], e) for e in entities) and \
                sum(1 for pat, _k, _v in hits if any(re.search(pat, e) for e in entities)) >= max(1, len(hits) // 2):
            return key
    return None


def charger_calls(intent: str, entities: list[str], platform: str | None, current: float,
                  device_id: str | None = None) -> list[dict[str, Any]]:
    """Start at a current, or stop - by the charger integration's own way where known, else its switch and number."""
    ctx = {"current": round(current), "device_id": device_id or ""}
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

"""Telling an inverter and a charger what to do - the same few intents for every brand.

Battery intents:
- "normal": the house first; the battery covers the house and stores solar surplus (self-use)
- "hold": keep what is in the battery (no discharging); solar may still fill it
- "charge": charge from the grid now, at a power, up to a target level

Charger intents: "charge" at a current (A), or "stop".

Each brand is a profile: for each intent, which control to set to what. Controls are found on the inverter's own
entities by pattern (select.*work_mode_priority …), so one profile fits every installation of that integration.
A brand that isn't built in gets a profile the user makes in the panel: pick the control and value for each intent.

Values may use {min_soc}, {soc}, {target}, {rate} (% of max power), {power_w}, {charge_a} (the charge power in amps at the battery's voltage), {current} and {house_w} (the house's
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
        # "Load first" lets the battery follow the house. The free-mode rates decide how hard it may discharge and how
        # much of the sun it may take: discharge 100 % when it should cover the house, 0 % when it holds; the sun may
        # always fill it to 100 %. Slot 1 (battery first) is let go, or a stuck slot keeps the battery from discharging.
        "normal": [(r"select\..*work_mode_priority$", "select", "Load first"), (r"number\..*load_first_stop_discharge$", "number", "{min_soc}"),
                   (r"select\..*battery_first_grid_charge$", "select", "Disabled"),
                   (r"number\..*free_mode_discharge_rate$", "number", "100"), (r"number\..*free_mode_charge_rate$", "number", "100"),
                   (r"number\..*load_first_stop_charge$", "number", "100"), (r"switch\..*battery_first_slot_1_enabled$", "off", None),
                   (r"switch\..*grid_first_slot_1_enabled$", "off", None)],  # selling's all-day time slot off again
        "hold": [(r"select\..*work_mode_priority$", "select", "Load first"), (r"number\..*load_first_stop_discharge$", "number", "{soc}"),
                 (r"select\..*battery_first_grid_charge$", "select", "Disabled"),
                 (r"number\..*free_mode_discharge_rate$", "number", "0"), (r"number\..*free_mode_charge_rate$", "number", "100"),
                 (r"number\..*load_first_stop_charge$", "number", "100"), (r"switch\..*battery_first_slot_1_enabled$", "off", None),
                   (r"switch\..*grid_first_slot_1_enabled$", "off", None)],  # selling's all-day time slot off again
        "optional": [r"number\..*free_mode_discharge_rate$", r"number\..*free_mode_charge_rate$", r"number\..*load_first_stop_charge$",
                     r"switch\..*grid_first_slot_1_enabled$"],
        # The mode first and the time slot last: SolarAssistant writes "Battery first" as an all-day slot (00:00-23:59),
        # which then put over the slot just written (21 November).
        "charge": [(r"select\..*work_mode_priority$", "select", "Battery first"),
                   (r"number\..*battery_first_charge_rate$", "number", "{rate}"),
                   (r"number\..*battery_first_stop_charge$", "number", "{target}"), (r"select\..*battery_first_grid_charge$", "select", "Enabled"),
                   (r"switch\..*battery_first_slot_1_enabled$", "on", None), (r"select\..*battery_first_slot_1_start$", "select", "{lease_from}"),
                   (r"select\..*battery_first_slot_1_end$", "select", "{lease_to}")],
        # Selling from the battery (only when the user turns it on).
        "export": [(r"select\..*work_mode_priority$", "select", "Grid first"),
                   (r"number\..*grid_first_discharge_rate$", "number", "{rate}"),
                   (r"number\..*grid_first_stop_discharge$", "number", "{target}"),
                   (r"switch\..*grid_first_slot_1_enabled$", "on", None),
                   (r"select\..*grid_first_slot_1_start$", "select", "{lease_from}"),
                   (r"select\..*grid_first_slot_1_end$", "select", "{lease_to}")],
    },
    "growatt_tlxh": {
        "name": "Growatt (MIN/MOD TL-XH)",
        "match": r"growatt",
        "models": r"TL-?XH|\bMIN\b|\bMOD\b|\bMID\b",
        "normal": [(r"select\..*(work_mode_priority|priority_mode|inverter_priority)$", "select", "Load first"),
                   (r"number\..*(load_first_stop_discharge|discharge_stop_soc)$", "number", "{min_soc}"),
                   (r"(select|switch)\..*(ac_charge|grid_charge).*$", "off", None),
                   (r"number\..*(grid_first_discharge_rate|discharge_power_rate)$", "number", "100"),
                   (r"number\..*(battery_first_charge_rate|charge_power_rate)$", "number", "100")],
        "hold": [(r"select\..*(work_mode_priority|priority_mode|inverter_priority)$", "select", "Load first"),
                 (r"number\..*(load_first_stop_discharge|discharge_stop_soc)$", "number", "{soc}"),
                 (r"(select|switch)\..*(ac_charge|grid_charge).*$", "off", None),
                 (r"number\..*(battery_first_charge_rate|charge_power_rate)$", "number", "100")],
        "charge": [(r"number\..*(battery_first_stop_charge|charge_stop_soc)$", "number", "{target}"),
                   (r"number\..*(battery_first_charge_rate|charge_power_rate)$", "number", "{rate}"),
                   (r"(select|switch)\..*(ac_charge|grid_charge).*$", "on", None),
                   (r"select\..*(work_mode_priority|priority_mode|inverter_priority)$", "select", "Battery first")],
        # Selling from the battery (only when the user turns it on).
        "export": [(r"number\..*(grid_first_stop_discharge|discharge_stop_soc)$", "number", "{target}"),
                   (r"number\..*(grid_first_discharge_rate|discharge_power_rate)$", "number", "{rate}"),
                   (r"select\..*(work_mode_priority|priority_mode|inverter_priority)$", "select", "Grid first")],
        "optional": [r"number\..*(battery_first_charge_rate|charge_power_rate)$", r"number\..*(grid_first_discharge_rate|discharge_power_rate)$"],
    },
    # Deye hybrid (also Sunsynk-built) via the Solarman integration (davidrapan/ha-solarman). Deye works with six
    # "Time of Use" programmes; each has a battery level it won't go below and whether it may charge from the grid.
    # All six are set alike, so whichever programme is running does what the plan wants - no clock times are touched.
    "solarman": {
        "name": "Deye (Solarman)",
        "match": r"deye|solarman",
        "models": r"deye|SUN-\d+K-SG|sg0\dlp|sg0\dhp",
        "normal": [(r"select\..*time_of_use$", "select", "Week"), (r"switch\..*battery_grid_charging$", "grid", None)]
        + [(rf"number\..*program_{n}_soc$", "number", "{min_soc}") for n in range(1, 7)]
        + [(rf"select\..*program_{n}_charging$", "select", "Disabled") for n in range(1, 7)],
        "hold": [(r"select\..*time_of_use$", "select", "Week"), (r"switch\..*battery_grid_charging$", "grid", None)]
        + [(rf"number\..*program_{n}_soc$", "number", "{soc}") for n in range(1, 7)]
        + [(rf"select\..*program_{n}_charging$", "select", "Disabled") for n in range(1, 7)],
        "charge": [(r"select\..*time_of_use$", "select", "Week"), (r"switch\..*battery_grid_charging$", "grid", None)]
        + [(rf"number\..*program_{n}_soc$", "number", "{target}") for n in range(1, 7)]
        + [(rf"select\..*program_{n}_charging$", "select", "Grid") for n in range(1, 7)]
        + [(r"number\..*battery_grid_charging_current$", "number", "{charge_a}")],
        # Selling from the battery (davidrapan/ha-solarman deye_hybrid): Work Mode "Export First" with its
        # "Export Surplus Power", every programme down to the target.
        "export": [(r"select\..*time_of_use$", "select", "Week"), (r"switch\..*battery_grid_charging$", "grid", None)]
        + [(rf"number\..*program_{n}_soc$", "number", "{target}") for n in range(1, 7)]
        + [(rf"select\..*program_{n}_charging$", "select", "Disabled") for n in range(1, 7)]
        + [(r"number\..*export_surplus_power$", "number", "{power_w}"),
           (r"select\..*(?<!energy_pattern_)work_mode$", "select", "Export First")],
        # The owner's own work mode (Zero Export To CT …) and export power are put back after selling.
        "restore": [r"select\..*(?<!energy_pattern_)work_mode$", r"number\..*export_surplus_power$"],
        # The grid charge current is limited to the planned power while charging; the owner's own is put back after.
        "restore_charge": [r"number\..*battery_grid_charging_current$"],
        "optional": [r"number\..*battery_grid_charging_current$"],
    },
    # Deye via ESPHome and local Modbus (klatremis/esphome-for-deye): the six "Time point" programmes, set alike.
    "deye_esphome": {
        "name": "Deye (ESPHome, local Modbus)",
        "match": r"deye|time_point_\d",
        "models": r"esphome|SG04LP3",
        "normal": [(r"switch\..*time_of_use$", "on", None), (r"switch\..*grid_charge$", "grid", None)]
        + [(rf"number\..*time_point_{n}_capacity$", "number", "{min_soc}") for n in range(1, 7)]
        + [(rf"switch\..*time_point_{n}_charge_enable$", "off", None) for n in range(1, 7)],
        "hold": [(r"switch\..*time_of_use$", "on", None), (r"switch\..*grid_charge$", "grid", None)]
        + [(rf"number\..*time_point_{n}_capacity$", "number", "{soc}") for n in range(1, 7)]
        + [(rf"switch\..*time_point_{n}_charge_enable$", "off", None) for n in range(1, 7)],
        "charge": [(r"switch\..*time_of_use$", "on", None), (r"switch\..*grid_charge$", "grid", None)]
        + [(rf"number\..*time_point_{n}_capacity$", "number", "{target}") for n in range(1, 7)]
        + [(rf"switch\..*time_point_{n}_charge_enable$", "on", None) for n in range(1, 7)]
        + [(r"number\..*maximum_battery_grid_charge_current$", "number", "{charge_a}")],
        # Selling (klatremis/esphome-for-deye): "Limit control mode" = "Selling first" with "Max Solar Sell Power",
        # every time point down to the target. The owner's own limit mode and sell power are put back after.
        "export": [(r"switch\..*time_of_use$", "on", None), (r"switch\..*grid_charge$", "grid", None)]
        + [(rf"number\..*time_point_{n}_capacity$", "number", "{target}") for n in range(1, 7)]
        + [(rf"switch\..*time_point_{n}_charge_enable$", "off", None) for n in range(1, 7)]
        + [(r"switch\..*solar_sell$", "on", None),
           (r"number\..*max_solar_sell_power$", "number", "{power_w}"),
           (r"select\..*limit_control_mode$", "select", "Selling first")],
        "restore": [r"select\..*limit_control_mode$", r"number\..*max_solar_sell_power$", r"switch\..*solar_sell$"],
        "restore_charge": [r"number\..*maximum_battery_grid_charge_current$"],
        "optional": [r"switch\..*solar_sell$", r"number\..*maximum_battery_grid_charge_current$"],
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
        "optional": [r"number\..*ess_max_discharging_limit$", r"number\..*ess_max_charging_limit$"],
        "match": r"sigen",
        "source": "integration",
        "normal": [(r"number\..*ess_max_discharging_limit$", "number", "{max_power_kw}"), (r"number\..*ess_max_charging_limit$", "number", "{max_charge_kw}"),
                   (r"switch\..*remote_ems.*$", "on", None), (r"select\..*remote_ems_control_mode$", "select", "Maximum Self Consumption")],
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
        # Victron's ESS settings go back to their defaults after about 10 minutes when set from Home Assistant
        # (a user saw it), so they are sent again every 4 minutes.
        "reassert_s": 240,
        "resets_itself": True,
        # The ESS controls often sit on another device than the battery level (Victron MQTT's "ESS" device, the level
        # from the GX device) - their names are distinctive, so they're looked for everywhere.
        "anywhere": True,
        "models": r"victron|multiplus|quattro|cerbo|venus|gx device|\bgx\b",
        "normal": [(r"switch\..*ess_force_charge$", "off", None),
                   (r"number\..*ess_maximum_discharge_power$", "number", "{max_power_w}"),
                   (r"number\..*ess_maximum_charge_power$", "number", "{max_charge_w}"),
                   (r"switch\..*ess_disable_charge$", "off", None)],
        "hold": [(r"switch\..*ess_force_charge$", "off", None),
                 (r"number\..*ess_maximum_discharge_power$", "number", "0"),
                 (r"number\..*ess_maximum_charge_power$", "number", "{max_charge_w}"),
                 (r"switch\..*ess_disable_charge$", "off", None)],
        "optional": [r"number\..*ess_maximum_charge_power$", r"switch\..*ess_disable_charge$"],
        "charge": [(r"number\..*ess_maximum_charge_power$", "number", "{power_w}"),
                   (r"switch\..*ess_force_charge$", "on", None)],
        # Selling from the battery (only when the user turns it on).
        "export": [(r"switch\..*ess_force_charge$", "off", None),
                   (r"number\..*ess_maximum_discharge_power$", "number", "{max_power_w}"),
                   (r"number\..*(grid_set_?point|acpowersetpoint)$", "number", "-{export_w}")],
        # The owner's own grid setpoint is remembered before selling and put back after.
        "restore": [r"number\..*(grid_set_?point|acpowersetpoint)$"],
    },
    # Megarevo (R-series hybrid) through SolarAssistant's MQTT: the inverter's own "Work mode" - Self Consumption,
    # Peak Shift or Battery Priority (Megarevo's manual). SolarAssistant shows only the discharge slots of Peak Shift,
    # not when to charge, so it can't be told to buy from the grid: the plan never does. The option names are matched
    # loosely ("Self consume" / "Self Consumption").
    "megarevo": {
        "name": "Megarevo (SolarAssistant)",
        "match": r"megarevo",
        "models": r"megarevo",
        "grid_charge": False,
        "normal": [(r"select\..*work_mode$", "select", "re:self.?consum")],
        "hold": [(r"select\..*work_mode$", "select", "re:batt?e?r?y?.?prior")],
        "charge": [(r"select\..*work_mode$", "select", "re:self.?consum")],
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
                   (r"number\..*min_discharge_level$", "number", "{min_soc}"), (r"number\..*max_charge_level$", "number", "100")],
        "hold": [(r"number\..*custom_load_power.*$", "number", "0"),
                 (r"number\..*min_discharge_level$", "number", "{soc}"), (r"number\..*max_charge_level$", "number", "100")],
        "optional": [r"number\..*max_charge_level$"],
        "charge": [(r"number\..*custom_load_power.*$", "number", "0"),
                   (r"number\..*max_charge_level$", "number", "{target}")],
        # Selling: a custom load above what the house uses - the rest goes out on the grid (at most 800 W, and only
        # where feed-in is allowed). Normal sets it back to the house.
        "export": [(r"number\..*custom_load_power.*$", "number", "{power_w}")],
    },
    # Huawei (wlcrs/huawei_solar): "Working Mode" (newer versions: "maximise_self_consumption", older: the label
    # "Maximise self consumption" - the control's own option is picked), maximum discharging power, and the
    # forcible_charge_soc service (needs the battery's device_id); "Stop forcible charge" ends a charge.
    "huawei_solar": {
        "name": "Huawei SUN2000 / LUNA2000",
        "match": r"huawei|sun2000|luna|batteries_",
        "source": "integration",
        "normal": [(r"button\..*stop_forcible_charge$", "press", None),
                   (r"select\..*(?<!emma_)working_mode(_settings)?$", "select", "re:maximi[sz]e.?self.?consum"),
                   (r"number\..*maximum_discharging_power$", "number", "{max_power_w}"),
                   (r"number\..*maximum_charging_power$", "number", "{max_charge_w}")],
        "hold": [(r"button\..*stop_forcible_charge$", "press", None),
                 (r"select\..*(?<!emma_)working_mode(_settings)?$", "select", "re:maximi[sz]e.?self.?consum"),
                 (r"number\..*maximum_discharging_power$", "number", "0"),
                 (r"number\..*maximum_charging_power$", "number", "{max_charge_w}")],
        "charge": [(r"number\..*maximum_discharging_power$", "number", "{max_power_w}"),
                   ("huawei_solar.forcible_charge_soc", "service", {"device_id": "{device_id}", "target_soc": "{target}", "power": "{power_w}"})],
        # Selling from the battery (only when the user turns it on): checked in the integration's source.
        "export": [(r"number\..*maximum_discharging_power$", "number", "{max_power_w}"),
                   ("huawei_solar.forcible_discharge_soc", "service", {"device_id": "{device_id}", "target_soc": "{target}", "power": "{power_w}"})],
        "optional": [r"number\..*maximum_charging_power$", r"select\..*(?<!emma_)working_mode(_settings)?$", r"button\..*stop_forcible_charge$"],
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
        # mkaiser's YAML package: template selects/numbers without a device - picked up by name (control.discover).
        "match": r"sungrow|sh\d+rt|ems_mode",
        # The forced command back to Stop too (as mkaiser's own self-consumption scene): left on "Forced charge" it
        # kept charging from the grid after a charge (issue #42).
        "normal": [(r"select\..*battery_forced_charge_discharge.*$", "select", "Stop (default)"),
                   (r"select\..*ems_mode.*$", "select", "Self-consumption mode (default)"),
                   (r"number\..*battery_max_discharge_power$", "number", "{max_power_w}"),
                   (r"number\..*battery_max_charge_power$", "number", "{max_charge_w}")],
        "hold": [(r"select\..*ems_mode.*$", "select", "Forced mode"), (r"select\..*battery_forced_charge_discharge.*$", "select", "Stop (default)")],
        "charge": [(r"select\..*ems_mode.*$", "select", "Forced mode"), (r"number\..*forced_charge_discharge_power.*$", "number", "{power_w}"),
                   (r"select\..*battery_forced_charge_discharge.*$", "select", "Forced charge")],
        # Selling from the battery (only when the user turns it on): checked in the integration's source.
        "export": [(r"select\..*ems_mode.*$", "select", "Forced mode"),
                   (r"number\..*forced_charge_discharge_power.*$", "number", "{power_w}"),
                   (r"select\..*battery_forced_charge_discharge.*$", "select", "Forced discharge")],
        "optional": [r"number\..*battery_max_discharge_power$", r"number\..*battery_max_charge_power$"],
    },
    # KRoperUK/sungrow-hass (domain "sungrow", iSolarCloud or local): the battery mode select only shows once the
    # integration has seen a battery. Its "Stop" is self-consumption - no real hold, so hold is a forced charge at 0 W.
    "sungrow_hass": {
        "name": "Sungrow (sungrow-hass)",
        "match": r"battery_mode|forced_dispatch_duration",
        "normal": [(r"select\..*battery_mode$", "select", "re:self.?consumption")],
        "hold": [(r"number\..*charge_discharge_power$", "number", "0"), (r"number\..*forced_dispatch_duration$", "number", "30"),
                 (r"select\..*battery_mode$", "select", "re:force.?charge")],
        "charge": [(r"number\..*charge_discharge_power$", "number", "{power_w}"), (r"number\..*forced_dispatch_duration$", "number", "30"),
                   (r"select\..*battery_mode$", "select", "re:force.?charge")],
        "export": [(r"number\..*charge_discharge_power$", "number", "{power_w}"), (r"number\..*forced_dispatch_duration$", "number", "30"),
                   (r"select\..*battery_mode$", "select", "re:force.?discharge")],
        "optional": [r"number\..*forced_dispatch_duration$"],
    },
    # myenergi libbi (CJNE/ha-myenergi): Normal / Stopped / Export; grid charging by the app's switch up to a target.
    "myenergi_libbi": {
        "name": "myenergi libbi",
        "match": r"libbi",
        "normal": [(r"switch\..*libbi.*charge_from_grid$", "off", None), (r"select\..*libbi.*operating_mode$", "select", "Normal")],
        "hold": [(r"switch\..*libbi.*charge_from_grid$", "off", None), (r"select\..*libbi.*operating_mode$", "select", "Stopped")],
        "charge": [(r"number\..*libbi.*charge_target$", "number", "{target}"), (r"switch\..*libbi.*charge_from_grid$", "on", None),
                   (r"select\..*libbi.*operating_mode$", "select", "Normal")],
        "export": [(r"switch\..*libbi.*charge_from_grid$", "off", None), (r"select\..*libbi.*operating_mode$", "select", "Export")],
        "optional": [r"number\..*libbi.*charge_target$"],
    },
    # Marstek Venus (ffunes/Marstek-Venus-Energy-Manager): its own loop off (manual mode), RS485 control on, then the
    # force mode ("None"/"stop", "Charge"/"charge" by version) with a power. Normal gives the battery back to it.
    "marstek_venus": {
        "name": "Marstek Venus",
        "match": r"marstek|rs485_control_mode|force_mode",
        "normal": [(r"select\..*force_mode$", "select", "re:^(none|stop)$"), (r"switch\..*rs485_control_mode$", "off", None),
                   (r"switch\..*manual_mode$", "off", None)],
        "hold": [(r"switch\..*manual_mode$", "on", None), (r"switch\..*rs485_control_mode$", "on", None),
                 (r"select\..*force_mode$", "select", "re:^(none|stop)$")],
        "charge": [(r"switch\..*manual_mode$", "on", None), (r"switch\..*rs485_control_mode$", "on", None),
                   (r"number\..*set_charge_power$", "number", "{power_w}"), (r"select\..*force_mode$", "select", "re:^charge$")],
        "export": [(r"switch\..*manual_mode$", "on", None), (r"switch\..*rs485_control_mode$", "on", None),
                   (r"number\..*set_discharge_power$", "number", "{power_w}"), (r"select\..*force_mode$", "select", "re:^discharge$")],
        "optional": [r"switch\..*manual_mode$"],
    },
    # Luxpower (ant0nkr/luxpower-ha-integration, lxp_modbus): AC charging to an end level; hold = the on-grid cut-off at
    # the level now; selling = forced discharge. Its time windows are the user's (set them to the whole day).
    "luxpower": {
        "name": "Luxpower (lxp_modbus)",
        "match": r"lxp|luxpower|ac_charge_end_soc|forced_discharge",
        "normal": [(r"switch\..*ac_charging$", "off", None), (r"switch\..*forced_discharge$", "off", None),
                   (r"number\..*on_grid_cut_off_soc$", "number", "{min_soc}")],
        "hold": [(r"switch\..*ac_charging$", "off", None), (r"switch\..*forced_discharge$", "off", None),
                 (r"number\..*on_grid_cut_off_soc$", "number", "{soc}")],
        "charge": [(r"switch\..*forced_discharge$", "off", None), (r"number\..*ac_charge_power$", "number", "{rate}"),
                   (r"number\..*ac_charge_end_soc$", "number", "{target}"), (r"switch\..*ac_charging$", "on", None)],
        "export": [(r"switch\..*ac_charging$", "off", None), (r"number\..*forced_discharge_power$", "number", "{rate}"),
                   (r"number\..*forced_discharge_soc_limit$", "number", "{min_soc}"), (r"switch\..*forced_discharge$", "on", None)],
    },
    # E3DC (torbennehmer/hacs-e3dc): one action with the mode - 0 normal, 1 idle, 4 charge from the grid, 2 discharge.
    # The integration repeats it every 10 s until normal is set again.
    "e3dc_rscp": {
        "name": "E3DC (RSCP)",
        "match": r"e3dc",
        "normal": [("e3dc_rscp.set_power_mode", "service", {"device_id": "{device_id}", "power_mode": "0"})],
        "hold": [("e3dc_rscp.set_power_mode", "service", {"device_id": "{device_id}", "power_mode": "1"})],
        "charge": [("e3dc_rscp.set_power_mode", "service", {"device_id": "{device_id}", "power_mode": "4", "power_value": "{power_w}"})],
        "export": [("e3dc_rscp.set_power_mode", "service", {"device_id": "{device_id}", "power_mode": "2", "power_value": "{power_w}"})],
    },
    "solaredge_modbus_multi": {
        "name": "SolarEdge (Modbus Multi)",
        "match": r"solaredge",
        # Remote control ends when its command timeout (1 hour) runs out - written again every 30 minutes.
        "reassert_s": 1800,
        "keepalive": True,
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
        # Hold: Self Use with the on-grid minimum at the battery's level now - "Back-up" may charge from the grid
        # (what the users' own profiles did instead). Normal puts the minimum back.
        # "Self Use" in foxess_modbus, "Self-Use" in other Fox integrations: either is picked.
        "normal": [(r"number\..*min_soc_on_grid$", "number", "{min_soc}"), (r"select\..*work_mode$", "select", "re:^self.?use$")],
        "hold": [(r"number\..*min_soc_on_grid$", "number", "{soc}"), (r"select\..*work_mode$", "select", "re:^self.?use$")],
        # Force charge/discharge power is in kW in foxess_modbus (0-5 kW on an H1-5.0) - watts were refused.
        "charge": [(r"number\..*force_charge_power$", "number", "{power_kw}"), (r"number\..*force_charge_max_soc$", "number", "{target}"),
                   (r"select\..*work_mode$", "select", "Force Charge")],
        # Selling from the battery (only when the user turns it on): checked in the integration's source.
        # The on-grid minimum back to the user's own first - hold leaves it at the level now, and the Fox won't go below it.
        "export": [(r"number\..*min_soc_on_grid$", "number", "{min_soc}"), (r"number\..*force_discharge_power$", "number", "{power_kw}"),
                   (r"select\..*work_mode$", "select", "Force Discharge")],
        "optional": [r"number\..*force_charge_power$", r"number\..*force_charge_max_soc$"],
        "source": "integration",
    },
    # Fox ESS through its cloud (macxq/foxess-ha, domain foxess), checked in its source (0.61.1) - not foxess_modbus:
    # its work modes are "Self-Use", "Feed-in", "Backup", "Peak Shaving"; "ForceCharge"/"ForceDischarge" are only
    # reachable through the Mode Scheduler (service foxess.set_schedule, one group from the lease's start to its end),
    # and the work mode can't be changed while the scheduler is on - so it is turned off first. 1,440 cloud calls a day.
    # Three installs were taken for foxess_modbus by their names and "Force Charge" was refused.
    "foxess": {
        "name": "Fox ESS (cloud)",
        "match": r"foxess|fox_ess",
        "source": "integration",
        "normal": [(r"switch\..*_mode_scheduler$", "off", None), (r"number\..*_min_soc_on_grid$", "number", "{min_soc}"),
                   (r"select\..*_work_mode$", "select", "re:^self.?use$")],
        "hold": [(r"switch\..*_mode_scheduler$", "off", None), (r"number\..*_min_soc_on_grid$", "number", "{soc}"),
                 (r"select\..*_work_mode$", "select", "re:^self.?use$")],
        "charge": [("foxess.set_schedule", "service", {"device_sn": "{serial}", "enable": True, "is_default": False, "groups": [
            {"enable": 1, "startHour": "{lease_from_h}", "startMinute": "{lease_from_m}", "endHour": "{lease_to_h}", "endMinute": "{lease_to_m}",
             "workMode": "ForceCharge", "extraParam": {"maxSoc": "{target}", "minSocOnGrid": "{min_soc}", "fdPwr": "{power_w}", "fdSoc": 100}}]})],
        # Selling from the battery (only when the user turns it on): down to the target at the power asked.
        "export": [("foxess.set_schedule", "service", {"device_sn": "{serial}", "enable": True, "is_default": False, "groups": [
            {"enable": 1, "startHour": "{lease_from_h}", "startMinute": "{lease_from_m}", "endHour": "{lease_to_h}", "endMinute": "{lease_to_m}",
             "workMode": "ForceDischarge", "extraParam": {"maxSoc": 100, "minSocOnGrid": "{min_soc}", "fdPwr": "{power_w}", "fdSoc": "{target}"}}]})],
        "optional": [r"switch\..*_mode_scheduler$"],
    },
    # Growatt via the cloud (built-in growatt_server, MIN/TLX): no work modes, but limits - how low it may discharge
    # on the grid, how full it may charge, how hard, and "Charge from grid". Entity names from a user's install.
    "growatt_server": {
        "name": "Growatt (cloud, growatt_server)",
        "match": r"battery_discharge_soc_limit_on_grid|charge_from_grid",
        "normal": [(r"number\..*battery_discharge_soc_limit_on_grid$", "number", "{min_soc}"),
                   (r"number\..*battery_charge_soc_limit$", "number", "100"), (r"switch\..*charge_from_grid$", "off", None),
                   (r"number\..*battery_discharge_power_limit$", "number", "100"), (r"number\..*battery_charge_power_limit$", "number", "100")],
        "hold": [(r"number\..*battery_discharge_soc_limit_on_grid$", "number", "{soc}"),
                 (r"number\..*battery_charge_soc_limit$", "number", "100"), (r"switch\..*charge_from_grid$", "off", None),
                 (r"number\..*battery_charge_power_limit$", "number", "100")],
        "charge": [(r"number\..*battery_charge_soc_limit$", "number", "{target}"),
                   (r"number\..*battery_charge_power_limit$", "number", "{rate}"), (r"switch\..*charge_from_grid$", "on", None)],
        "optional": [r"number\..*battery_discharge_power_limit$", r"number\..*battery_charge_power_limit$"],
    },
    # Anker SOLIX Solarbank 2/3/4 and Max AC (thomluther/ha-anker-solix, the cloud), checked in its source (3.9.2).
    # The usage mode's options are its keys: "smartmeter", "smart", "manual", "backup" … Normal: self consumption with
    # the smart meter. Hold: "manual" with the home load preset at 0 W (the sun goes to the battery). Charge: "backup",
    # the AC models' charging from the grid at full power (an SB2 Pro/Plus has no such option and can't). Selling:
    # "manual" at a set power to the house. Through the cloud: a change shows after about 5 minutes.
    "anker_solix": {
        "name": "Anker SOLIX (Solarbank)",
        "match": r"solarbank|anker_solix",
        "source": "integration",
        "normal": [(r"select\..*_usage_mode$", "select", "re:^smart(meter)?$")],
        "hold": [(r"select\..*_usage_mode$", "select", "manual"), (r"number\..*_system_load_preset$", "number", "0")],
        "charge": [(r"select\..*_usage_mode$", "select", "backup")],
        "export": [(r"select\..*_usage_mode$", "select", "manual"), (r"number\..*_system_load_preset$", "number", "{power_w}")],
    },
    # GivEnergy through GivTCP (britkat1980/giv_tcp, MQTT: select.givtcp_<serial>_mode …), checked in its source (3.6.14).
    # Not its "Force Charge"/"Force Export": those put the old settings back by themselves afterwards and would undo
    # Energy Pilot's. Instead: the mode, charge/discharge slot 1 and the rates (W; GivTCP rounds them to whole % of the
    # battery, at most 50 %). Hold: discharge rate 0 - the sun may still charge. "Eco" sets the reserve to 4 %:
    # Energy Pilot keeps its own minimum. The inverter stops at the lower of the targets: slot 1's is set too (#576).
    "givtcp": {
        "name": "GivEnergy (GivTCP)",
        "match": r"givtcp",
        "source": "integration",
        "normal": [(r"select\..*givtcp\d?_[a-z0-9]+_mode$", "select", "Eco"), (r"switch\..*enable_charge_schedule$", "off", None),
                   (r"switch\..*enable_discharge_schedule$", "off", None),
                   (r"number\..*battery_charge_rate$", "number", "{max_charge_w}"), (r"number\..*battery_discharge_rate$", "number", "{max_power_w}")],
        "hold": [(r"select\..*givtcp\d?_[a-z0-9]+_mode$", "select", "Eco"), (r"switch\..*enable_charge_schedule$", "off", None),
                 (r"switch\..*enable_discharge_schedule$", "off", None),
                 (r"number\..*battery_charge_rate$", "number", "{max_charge_w}"), (r"number\..*battery_discharge_rate$", "number", "0")],
        "charge": [(r"select\..*givtcp\d?_[a-z0-9]+_mode$", "select", "Eco"), (r"number\..*givtcp\d?_[a-z0-9]+_target_soc$", "number", "{target}"),
                   (r"number\..*charge_target_soc_1$", "number", "{target}"),
                   (r"select\..*charge_start_time_slot_1$", "select", "{lease_from}:00"), (r"select\..*charge_end_time_slot_1$", "select", "{lease_to}:00"),
                   (r"number\..*battery_charge_rate$", "number", "{power_w}"), (r"switch\..*enable_charge_schedule$", "on", None)],
        # Selling from the battery (only when the user turns it on).
        "export": [(r"select\..*discharge_start_time_slot_1$", "select", "{lease_from}:00"),
                   (r"select\..*discharge_end_time_slot_1$", "select", "{lease_to}:00"),
                   (r"number\..*battery_discharge_rate$", "number", "{power_w}"), (r"switch\..*enable_discharge_schedule$", "on", None),
                   (r"select\..*givtcp\d?_[a-z0-9]+_mode$", "select", "Timed Export")],
        "optional": [r"number\..*charge_target_soc_1$", r"switch\..*enable_discharge_schedule$"],
    },
    # GivEnergy (cdpuk/givenergy-local): charging is a "timed charge" (service, needs the inverter's device_id) with
    # a charge target; hold pauses discharging.
    "givenergy_local": {
        "name": "GivEnergy (GivEnergy Local)",
        "match": r"givenergy",
        "source": "integration",
        "normal": [("givenergy_local.activate_mode_eco", "service", {"device_id": "{device_id}"}), ("givenergy_local.disable_timed_charge", "service", {"device_id": "{device_id}"}),
                   (r"select\..*battery_pause_mode$", "select", "Not Paused"), (r"number\..*battery_charge_power_limit$", "number", "{max_charge_w}"),
                   (r"number\..*battery_discharge_power_limit$", "number", "{max_power_w}")],
        "hold": [("givenergy_local.activate_mode_eco", "service", {"device_id": "{device_id}"}), ("givenergy_local.disable_timed_charge", "service", {"device_id": "{device_id}"}),
                 (r"select\..*battery_pause_mode$", "select", "Pause Discharge"), (r"number\..*battery_charge_power_limit$", "number", "{max_charge_w}")],
        "charge": [(r"select\..*battery_pause_mode$", "select", "Not Paused"),
                   (r"number\..*battery_charge_power_limit$", "number", "{power_w}"),
                   ("givenergy_local.enable_timed_charge", "service",
                    {"device_id": "{device_id}", "start_time": "{lease_from}", "end_time": "{lease_to}", "charge_target": "{target}"})],
        # Selling from the battery (only when the user turns it on): checked in the integration's source.
        "export": [(r"select\..*battery_pause_mode$", "select", "Not Paused"),
                   ("givenergy_local.activate_mode_timed_export", "service", {"device_id": "{device_id}", "start_time": "{lease_from}", "end_time": "{lease_to}"})],
        "optional": [r"number\..*battery_charge_power_limit$", r"number\..*battery_discharge_power_limit$"],
    },
    # Solis (Pho3niX90/solis_modbus): remote-control force charge with its power and timeout (1-30 min, so it is
    # re-sent every 10 minutes); hold is a force charge at 0 W, which stops discharging.
    "solis_modbus": {
        "name": "Solis (Solis Modbus)",
        "match": r"solis",
        "source": "integration",
        "reassert_s": 600,
        "keepalive": True,  # the timer only starts again when written - so written even if HA shows the value
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
    # GoodWe (Home Assistant's own goodwe integration, ET/EH/BT/BH hybrids): the inverter's operation mode, with the
    # eco mode power (% of the inverter's power) and the eco mode level (%) - written first, the mode reads them when it
    # is set. Checked by a user in New Zealand (GoodWe ET, own profile: normal, keep and charge all green).
    "goodwe": {
        "name": "GoodWe (ET/EH/BT/BH)",
        "match": r"goodwe|inverter_operation_mode|eco_mode_power",
        "source": "integration",
        "normal": [(r"select\..*(inverter_)?operation_mode$", "select", "re:^general")],
        "hold": [(r"number\..*eco_mode_power$", "number", "0"),
                 (r"select\..*(inverter_)?operation_mode$", "select", "re:^eco.?discharge")],
        "charge": [(r"number\..*eco_mode_power$", "number", "{rate}"), (r"number\..*eco_mode_soc$", "number", "{target}"),
                   (r"select\..*(inverter_)?operation_mode$", "select", "re:^eco.?charge")],
        # Selling from the battery (only when the user turns it on): eco discharge at a power, down to a level.
        "export": [(r"number\..*eco_mode_power$", "number", "{rate}"), (r"number\..*eco_mode_soc$", "number", "{target}"),
                   (r"select\..*(inverter_)?operation_mode$", "select", "re:^eco.?discharge")],
    },
    # GoodWe EMS (the experimental GoodWe integration, newer firmware): the EMS mode with a power limit in W - the newer
    # way GoodWe controls its inverters, next to the operation mode above (some show both; the operation mode is picked
    # by itself, EMS is chosen in the settings). Entity names from a user's GW10KL-ET; the self-test checks each step.
    "goodwe_ems": {
        "name": "GoodWe EMS (experimental integration)",
        "match": r"ems_mode|ems_power_limit",
        "source": "integration",
        "normal": [(r"select\..*ems_mode$", "select", "re:^auto$")],
        "hold": [(r"select\..*ems_mode$", "select", "re:^battery_standby$|standby")],
        "charge": [(r"number\..*ems_power_limit$", "number", "{power_w}"),
                   (r"select\..*ems_mode$", "select", "re:^charge_battery$")],
        # Selling from the battery (only when the user turns it on).
        "export": [(r"number\..*ems_power_limit$", "number", "{power_w}"),
                   (r"select\..*ems_mode$", "select", "re:^discharge_battery$")],
    },
    # Alpha ESS (Poshy163/homeassistant-alphaESS, cloud): charge and discharge windows by service, with the serial.
    # Alpha ESS cloud (CharlesGillanders/homeassistant-alphaESS). Its periodic schedule: times in whole quarters,
    # a period written 00:00-00:00 is deleted (and an empty list is refused), a new period needs its power in W, and
    # charge and discharge windows may not overlap. A discharge window is when the battery MAY discharge - so "hold"
    # is a discharge window far from now. The windows come from the clock (alpha_windows): charging from now for 4 h,
    # the parked windows 12 h away, each on its own quarter.
    # Kostal Plenticore (hybrid G1-G3 and BI) through Kostal Plenticore Battery Control (mbuhansen/kostal_plenticore_
    # battery_control, domain kostal_modbus_control). The inverter's battery management must be "External via protocol
    # (Modbus TCP)". The four control switches are mutually exclusive in the integration (one on turns the others off),
    # and the integration itself keeps the Modbus session alive while one is on - nothing to send again. All off hands
    # the battery back to the inverter's own self-use; Block Discharge holds the SoC (the sun may still fill it); Charge
    # Start / Discharge Start charge or discharge at the rate in watts. The integration waits Modbus timeout + 15 s
    # after a stop before it writes again, so a change of intent takes up to a minute to show.
    # With Predbat in an active control mode, Charge Start follows Predbat's best_charge_limit instead - Predbat must be
    # off (checks.py warns about it).
    "kostal_modbus_control": {
        "name": "Kostal Plenticore (Modbus)",
        "match": r"plenticore|kostal",
        "normal": [(r"switch\..*_charge_start$", "off", None), (r"switch\..*_discharge_start$", "off", None),
                   (r"switch\..*_block_charge$", "off", None), (r"switch\..*_block_discharge$", "off", None)],
        "hold": [(r"switch\..*_block_discharge$", "on", None)],
        "charge": [(r"number\..*_set_charge_rate$", "number", "{power_w}"), (r"switch\..*_charge_start$", "on", None)],
        # Selling from the battery (only when the user turns it on).
        "export": [(r"number\..*_set_discharge_rate$", "number", "{power_w}"), (r"switch\..*_discharge_start$", "on", None)],
        # The owner's own rates are put back after charging and selling.
        "restore_charge": [r"number\..*_set_charge_rate$"],
        "restore": [r"number\..*_set_discharge_rate$"],
        # Asleep at night ("Off") the inverter first runs StartUp and GridCheck before it charges - up to ~10 min.
        # The self-test waits for FeedIn (state 6) before it judges.
        "ready": (r"sensor\..*_inverter_state$", r"^(6|FeedIn)$"),
        # The integration's own SoC limits, which it keeps writing to the inverter while they are in use: the battery
        # won't go below the minimum or above the maximum, whatever is asked - so the plan stays inside them too.
        # 5 % and 100 % mean "not in use" (the inverter's own), which changes nothing.
        "limits": (r"number\..*_battery_minimum_soc_limit$", r"number\..*_battery_maximum_soc_limit$"),
        # The most the integration lets the battery charge or discharge (worked out from the battery's voltage and
        # current, in W): the battery's power when none is set, and the cap on what is set.
        "max_power": r"sensor\..*_battery_max_control_power$",
        # The house's main fuse in amps, as set in the integration (its own grid protection uses it): Energy Pilot's
        # import limit is set from it while that is still the 10 kW it starts with (autofix.py).
        "fuse": r"number\..*_house_fuse_size$",
    },
    "alphaess": {
        "name": "Alpha ESS (cloud)",
        "match": r"alpha_?ess",
        "source": "integration",
        "normal": [("alphaess.setbatterycharge", "service", {"serial": "{serial}", "enabled": False, "cp1start": "{park_c_from}", "cp1end": "{park_c_to}",
                                                             "cp2start": "00:00", "cp2end": "00:00", "chargestopsoc": 100, "cp1power": "{max_charge_w}"}),
                   ("alphaess.setbatterydischarge", "service", {"serial": "{serial}", "enabled": False, "dp1start": "{park_d_from}", "dp1end": "{park_d_to}",
                                                                "dp2start": "00:00", "dp2end": "00:00", "dischargecutoffsoc": "{min_soc}", "dp1power": "{max_power_w}"})],
        "hold": [("alphaess.setbatterycharge", "service", {"serial": "{serial}", "enabled": False, "cp1start": "{park_c_from}", "cp1end": "{park_c_to}",
                                                           "cp2start": "00:00", "cp2end": "00:00", "chargestopsoc": 100, "cp1power": "{max_charge_w}"}),
                 ("alphaess.setbatterydischarge", "service", {"serial": "{serial}", "enabled": True, "dp1start": "{park_d_from}", "dp1end": "{park_d_to}",
                                                              "dp2start": "00:00", "dp2end": "00:00", "dischargecutoffsoc": "{soc}", "dp1power": "{max_power_w}"})],
        "charge": [("alphaess.setbatterydischarge", "service", {"serial": "{serial}", "enabled": False, "dp1start": "{park_d_from}", "dp1end": "{park_d_to}",
                                                                "dp2start": "00:00", "dp2end": "00:00", "dischargecutoffsoc": "{min_soc}", "dp1power": "{max_power_w}"}),
                   # A period may not run over midnight (start after end never starts): split in two, before and after it.
                   ("alphaess.setbatterycharge", "service", {"serial": "{serial}", "enabled": True, "cp1start": "{now_from}", "cp1end": "{now_to}",
                                                             "cp2start": "{now2_from}", "cp2end": "{now2_to}", "chargestopsoc": "{target}", "cp1power": "{power_w}"})],
    },
}

# Chargers: almost every integration has a switch to start/stop and a number for the current.
CHARGER_SWITCH = r"switch\..*(charg|enable|is_enabled|charge_control|charging_allowed|start_stop|pause|resume)"
CHARGER_CURRENT = r"number\..*(current|ampere|amp|charging_limit|dynamic_limit)"
CHARGER_CURRENT_SELECT = r"select\..*(current|ampere|courant|strom)"  # VEVOR (Tuya) and others: the current as a list
# Chargers by integration - from each integration's own source code. The current is in amps; {device_id} is the
# charger's device in Home Assistant. Not on the list: the generic switch + number above.
CHARGER_SERVICES = {
    "keba": {"charge": [("keba.set_current", "service", {"current": "{current}"}), ("keba.enable", "service", {})],
             "stop": [("keba.disable", "service", {})]},
    # Easee (nordicopen/easee_hass): actions with the charger's device
    # Easee charges at the lower of the charger's and the circuit's dynamic limit: both are set (the circuit's on
    # all three phases - a car on one phase takes only its own). Last, so charging has started if it's refused.
    "easee": {"charge": [("easee.set_charger_dynamic_limit", "service", {"device_id": "{device_id}", "current": "{current}"}),
                         ("easee.action_command", "service", {"device_id": "{device_id}", "action_command": "resume"}),
                         ("easee.set_circuit_dynamic_limit", "service", {"device_id": "{device_id}", "current_p1": "{current}",
                                                                          "current_p2": "{current}", "current_p3": "{current}"})],
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
    # evcc (marq24/ha-evcc): the loadpoint's "Mode" - now / off (evcc keeps its own current and phases)
    # Handed back to evcc's own planning ("smart"; "pv" in evcc before 0.200) when Energy Pilot lets go - else it would
    # stay at "off" or "now" and the owner's evcc plans would stop working.
    "evcc_intg": {"charge": [(r"select\..*_mode$", "select", "now")], "stop": [(r"select\..*_mode$", "select", "off")],
                  "hand_back": [(r"select\..*_mode$", "select", "re:^(smart|pv)$")]},
    # Hypervolt (gndean/home-assistant-hypervolt-charger): "Activation Mode" starts and stops it (Plug and Charge /
    # Schedule Charge - its own schedule then decides, so keep it empty), "Max Current" the speed, Boost = full power
    # (its Eco modes would only use the sun the house battery leaves)
    "hypervolt_charger": {"charge": [(r"select\..*charge_mode$", "select", "Boost"), (r"number\..*max_current$", "number", "{current}"),
                                     (r"select\..*activation_mode$", "select", "Plug and Charge")],
                          "stop": [(r"select\..*activation_mode$", "select", "Schedule Charge")]},
    # myenergi zappi (CJNE/ha-myenergi): "Charge Mode" Fast / Stopped (no current control)
    "myenergi": {"charge": [(r"select\..*charge_mode$", "select", "Fast")], "stop": [(r"select\..*charge_mode$", "select", "Stopped")]},
}


LEAD_MIN = 30  # a new window starts this long before the quarter now: the inverter is well inside it at once
LEASE_LEAD_MIN = 90  # the inverter's own slot (Growatt, GivEnergy) starts this much earlier still: inside it also with
# a clock up to 2 hours slow. A start in the past changes nothing with a right clock - the slot is only turned on when
# the plan's block begins, and off again when it ends. (Alpha ESS runs on the cloud's clock: not needed there.)
CAP_H = 3  # a window never runs further ahead than this (in whole hours, so it isn't moved every quarter)
PAD_H = 2  # the inverter's slot ends this long after the plan's block: a clock that runs fast (21 November: a Growatt
# 70 minutes ahead, never moved to winter time) ended the slot early. Energy Pilot ends the block itself on time.


def quarter(now: Any) -> Any:
    return now.replace(minute=now.minute - now.minute % 15, second=0, microsecond=0)


def window_start(now: Any) -> Any:
    """Where a new charge (or sell) window starts: a little before now, never before midnight."""
    from datetime import timedelta

    q = quarter(now)
    return max(q - timedelta(minutes=LEAD_MIN), q.replace(hour=0, minute=0))


def alpha_windows(now: Any, start: Any = None, end: Any = None) -> dict[str, str]:
    """The inverter's own time windows. Charging (or selling) runs from where the plan's block began to where it ends:
    written once and left alone while the block lasts - not moved on every quarter (a Growatt went back to Load first
    for minutes each time its slot was moved to start at the quarter now). Without a block: from a little before now,
    75 minutes ahead (Alpha ESS: 4 h). The parked Alpha windows are 12 h away, apart."""
    from datetime import timedelta

    q = quarter(now)
    hm = lambda d: d.strftime("%H:%M")  # noqa: E731
    s = start if start is not None and start <= now and start.date() == q.date() else window_start(now)
    cap = q.replace(minute=0) + timedelta(hours=CAP_H + 1)  # 3-4 h ahead, moved once an hour at most
    if end is not None:
        alpha_end = max(min(end, cap), q + timedelta(minutes=30))
        e = max(min(end + timedelta(hours=PAD_H), cap + timedelta(hours=PAD_H)), q + timedelta(minutes=30))
    else:
        e, alpha_end = q + timedelta(minutes=75), q + timedelta(hours=4)
    if alpha_end.date() == q.date():
        win = {"now_from": hm(s), "now_to": hm(alpha_end), "now2_from": "00:00", "now2_to": "00:00"}
    elif q.hour == 23 and q.minute == 45:  # the last quarter: from midnight (period 2 stays empty)
        win = {"now_from": "00:00", "now_to": hm(alpha_end), "now2_from": "00:00", "now2_to": "00:00"}
    else:  # over midnight: until 23:45, and from 00:00 on (AlphaESS takes periods within one day only)
        win = {"now_from": hm(s), "now_to": "23:45", "now2_from": "00:00", "now2_to": hm(alpha_end)}
    # A lease: should Energy Pilot, Home Assistant or the network stop, the slot runs out and the inverter goes back to
    # its normal running by itself - an order is never left standing all day (Growatt, GivEnergy).
    ls = max(s - timedelta(minutes=LEASE_LEAD_MIN), q.replace(hour=0, minute=0))
    lease = {"lease_from": hm(ls), "lease_to": hm(e) if e.date() == q.date() else "23:59"}
    for k in ("lease_from", "lease_to"):  # as numbers too (Fox ESS's cloud scheduler takes hour and minute apart)
        lease[k + "_h"], lease[k + "_m"] = (int(x) for x in lease[k].split(":"))
    return {**win, **lease,
            "park_c_from": hm(q + timedelta(hours=12)), "park_c_to": hm(q + timedelta(hours=12, minutes=15)),
            "park_d_from": hm(q + timedelta(hours=12, minutes=30)), "park_d_to": hm(q + timedelta(hours=12, minutes=45))}


def fill(value: Any, ctx: dict[str, Any]) -> Any:
    if isinstance(value, str) and re.fullmatch(r"-?\d+(?:\.\d+)?", value):
        return float(value) if "." in value else int(value)  # a plain number in a profile ("0")
    if isinstance(value, str) and "{" in value:
        out = value.format(**{k: (round(v, 2) if isinstance(v, float) else v) for k, v in ctx.items()})
        if re.fullmatch(r"\{(serial|\w*_?id)\}", value):
            return str(out)  # an identifier stays text, even "45" (Easee refuses a number as device_id)
        try:
            return float(out) if "." in out else int(out)
        except ValueError:
            return out
    if isinstance(value, dict):
        return {k: fill(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [fill(v, ctx) for v in value]
    return value


# An entity's id is in the user's language ("number.wallbox_maximal_laddningsstrom" in Swedish); the integration's own
# key for it is not ("maximum_charging_current"). The controller fills this from the entity registry: entity -> a
# second name built from that key, which the patterns are matched against as well.
ALIASES: dict[str, str] = {}


def alias_for(entity_id: str, translation_key: str | None) -> str | None:
    return f"{entity_id.split('.')[0]}.tk_{translation_key}" if translation_key else None


def hit(pattern: str, entity: str) -> bool:
    """The pattern matches the entity's id, or its name in the integration's own words (any language)."""
    return bool(re.search(pattern, entity) or ((a := ALIASES.get(entity)) and re.search(pattern, a)))


def _find(pattern: str, entities: list[str]) -> str | None:
    if "." in pattern and not any(c in pattern for c in "\\*^$[(+"):
        return pattern if pattern in entities else None  # an exact entity (custom profiles)
    return next((e for e in entities if re.search(pattern, e)), None) or next((e for e in entities if hit(pattern, e)), None)


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
            try:
                calls.append({"domain": domain, "service": "set_value", "data": {"entity_id": entity, "value": fill(value, ctx)}})
            except KeyError:  # a value this plan doesn't give (no {charge_a} for a second inverter of another make)
                continue
        elif kind == "grid":
            # Deye's global grid-charge switch follows the setting "may charge from the grid" - set, not toggled:
            # the programmes decide when (each "Grid" or "Disabled").
            on = bool(ctx.get("grid_charge", True))
            calls.append({"domain": domain, "service": "turn_on" if on else "turn_off", "data": {"entity_id": entity}})
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
        return sum(1 for pat, _k, _v in hits if any(hit(pat, e) for e in entities)) >= max(1, len(hits) // 2)

    for key, p in PROFILES.items():
        # The integration's name only counts when its controls are there too: Solarman serves Deye and Sofar alike.
        if key in platforms and fits(p):
            return key
    for key, p in PROFILES.items():
        hits = [s for steps in (p["normal"], p["hold"], p["charge"]) for s in steps if s[1] != "service"]
        if any(hit(p["match"], e) for e in entities) and \
                sum(1 for pat, _k, _v in hits if any(hit(pat, e) for e in entities)) >= max(1, len(hits) // 2):
            return key
    return None


def pick_option(pattern: str, options: list[str]) -> str | None:
    """The first option that matches the pattern, ignoring case."""
    return next((o for o in options if re.search(pattern, str(o), re.I)), None)


def _amp_option(options: list[str], current: float) -> str | None:
    """The highest current in the list that isn't above the wanted one (else the lowest): "16A", "16 A", "16"."""
    vals = []
    for o in options or []:
        m = re.search(r"\d+", str(o))
        if m:
            vals.append((int(m.group()), o))
    if not vals:
        return None
    under = [v for v in vals if v[0] <= current + 0.01]
    return max(under)[1] if under else min(vals)[1]


def phase_control(entities: list[str], states: dict[str, Any] | None) -> dict[str, Any] | None:
    """The charger's own 1/3-phase choice, when it has one Energy Pilot can read back: a select named for phases
    (evcc "phases_configured", go-e "phase_switch_mode" ...) with one option for 1 phase and one for 3 -
    {"entity", "1": option, "3": option, "now": 1 | 3 | None}. Chargers without it are never switched."""
    one = re.compile(r"(^|[^0-9])1([^0-9]|$)|single|one|^en|1p", re.I)
    three = re.compile(r"(^|[^0-9])3([^0-9]|$)|three|^tre|3p", re.I)
    # A switch "force 1 phase" (Peblar's force_single_phase, Dutch "dwing_enkelvoudige_fase_af"): on = 1, off = 3.
    for e in entities or []:
        if e.startswith("switch.") and re.search(r"(single|enkel|einphas|enfas|one|1).*(phase|fase)|(phase|fase).*(single|enkel|1)", e, re.I):
            cur = ((states or {}).get(e) or {}).get("state")
            return {"entity": e, "switch": True, "1": "on", "3": "off", "now": 1 if cur == "on" else 3 if cur == "off" else None}
    for e in entities or []:
        if not e.startswith("select.") or not re.search(r"phas|fase", e, re.I):
            continue
        st = (states or {}).get(e) or {}
        opts = [str(o) for o in (st.get("attributes") or {}).get("options") or []]
        o1 = next((o for o in opts if one.search(o) and not three.search(o) and "auto" not in o.lower()), None)
        o3 = next((o for o in opts if three.search(o) and not one.search(o) and "auto" not in o.lower()), None)
        if o1 and o3:
            cur = str(st.get("state"))
            return {"entity": e, "1": o1, "3": o3, "now": 1 if cur == o1 else 3 if cur == o3 else None}
    return None


def lowest_amps(entities: list[str], states: dict[str, Any] | None) -> int | None:
    """The charger's lowest current when it only takes fixed steps (a select: 8/10/13/16 A) or has a minimum."""
    for e in entities or []:
        a = ((states or {}).get(e) or {}).get("attributes") or {}
        if hit(CHARGER_CURRENT_SELECT, e):
            vals = [int(m.group()) for o in a.get("options") or [] if (m := re.search(r"\d+", str(o)))]
            if vals:
                return min(vals)
        elif hit(CHARGER_CURRENT, e) and a.get("min") not in (None, ""):
            try:
                return int(float(a["min"]) + 0.999)
            except (TypeError, ValueError):
                pass
    return None


def charger_switch(entities: list[str], lone_ok: bool = False) -> str | None:
    """The switch that starts and stops the charger: one named for it - or, on the charger's (or its power meter's)
    own device, its only switch (a Shelly or a smart plug the charger is plugged into)."""
    named = next((e for e in entities if hit(CHARGER_SWITCH, e)), None)
    if named or not lone_ok:
        return named
    switches = [e for e in entities if e.startswith("switch.")]
    return switches[0] if len(switches) == 1 else None


def charger_hand_back(platform: str | None, entities: list[str]) -> list[dict[str, Any]]:
    """What gives the charger back to its own planning when Energy Pilot lets go (evcc: its "smart" mode). Most
    chargers have none: they are left as they are."""
    steps = (CHARGER_SERVICES.get(platform or "") or {}).get("hand_back")
    return resolve(steps, entities, {}) if steps else []


def charger_calls(intent: str, entities: list[str], platform: str | None, current: float,
                  device_id: str | None = None, states: dict[str, Any] | None = None,
                  switch: str | None = None) -> list[dict[str, Any]]:
    """Start at a current, or stop - by the charger integration's own way where known, else its switch and number."""
    ctx = {"current": round(current), "device_id": device_id or ""}
    if platform in CHARGER_SERVICES:
        return resolve(CHARGER_SERVICES[platform][intent], entities, ctx)
    switch = switch or charger_switch(entities)
    number = next((e for e in entities if hit(CHARGER_CURRENT, e)), None)
    calls = []
    paused = switch is not None and hit(r"pause", switch)
    if intent == "charge":
        if number:
            calls.append({"domain": "number", "service": "set_value", "data": {"entity_id": number, "value": round(current)}})
        elif (sel := next((e for e in entities if hit(CHARGER_CURRENT_SELECT, e)), None)) and states is not None:
            opts = ((states.get(sel) or {}).get("attributes") or {}).get("options") or []
            if (opt := _amp_option(opts, current)) is not None:
                calls.append({"domain": "select", "service": "select_option", "data": {"entity_id": sel, "option": opt}})
        if switch:
            calls.append({"domain": "switch", "service": "turn_off" if paused else "turn_on", "data": {"entity_id": switch}})
    elif switch:
        calls.append({"domain": "switch", "service": "turn_on" if paused else "turn_off", "data": {"entity_id": switch}})
    return calls

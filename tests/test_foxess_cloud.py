"""Fox ESS through its cloud (macxq/foxess-ha, domain foxess) is not foxess_modbus: "Force Charge" isn't a work mode
there (three installs had it refused) - charging and selling go through its Mode Scheduler service."""

from datetime import datetime

from energy_pilot import adapters as A

CLOUD = ["number.foxess_min_soc", "number.foxess_min_soc_on_grid", "select.foxess_work_mode", "switch.foxess_mode_scheduler"]
MODBUS = ["number.foxess_min_soc_on_grid", "select.foxess_work_mode", "number.foxess_force_charge_power", "number.foxess_force_discharge_power"]


def test_cloud_is_told_from_modbus():
    assert A.guess_profile(CLOUD, {"foxess"}) == "foxess"
    assert A.guess_profile(MODBUS, {"foxess_modbus"}) == "foxess_modbus"
    assert A.guess_profile(MODBUS, {"foxess_modbus", "foxess"}) == "foxess_modbus"  # both installed: Modbus steers


def test_cloud_steps():
    ctx = {"serial": "60JH50203B2A038", "target": 95, "min_soc": 10, "soc": 60, "power_w": 3000,
           **A.alpha_windows(datetime(2026, 11, 24, 1, 7), datetime(2026, 11, 24, 0, 30), datetime(2026, 11, 24, 3, 0))}
    p = A.PROFILES["foxess"]
    hold = A.resolve(p["hold"], CLOUD, ctx)
    assert [c["service"] for c in hold] == ["turn_off", "set_value", "select_option"]  # the scheduler off before the mode
    assert hold[1]["data"]["value"] == 60
    (charge,) = A.resolve(p["charge"], CLOUD, ctx)
    assert (charge["domain"], charge["service"]) == ("foxess", "set_schedule")
    g = charge["data"]["groups"][0]
    assert charge["data"]["device_sn"] == "60JH50203B2A038" and g["workMode"] == "ForceCharge"
    assert (g["startHour"], g["startMinute"]) == (ctx["lease_from_h"], ctx["lease_from_m"]) and isinstance(g["endHour"], int) and g["endHour"] >= 3 and g["extraParam"]["maxSoc"] == 95
    (export,) = A.resolve(p["export"], CLOUD, {**ctx, "target": 30})
    assert export["data"]["groups"][0]["workMode"] == "ForceDischarge" and export["data"]["groups"][0]["extraParam"]["fdSoc"] == 30

"""#61: a Fox that discharges but sells nothing (export limit) isn't a fault; #62-64: a Deye model without Solarman's
controls doesn't get the Solarman profile."""
import asyncio

from energy_pilot import adapters
from energy_pilot.selftest import SelfTest
from test_selftest_offline import Ctl, Ov


def test_deye_without_solarman_controls_gets_no_solarman_profile():
    deye_modbus = ["sensor.deye_sun_12k_sg05lp3_battery_soc", "sensor.deye_sun_12k_sg05lp3_battery_power",
                   "number.deye_sun_12k_sg05lp3_max_charge_current"]
    assert adapters.guess_profile(deye_modbus, {"deye_modbus"}, "SUN-12K-SG05LP3") != "solarman"


def test_deye_with_solarman_controls_still_gets_it():
    ents = [f"number.inv_program_{n}_soc" for n in range(1, 7)] + [f"select.inv_program_{n}_charging" for n in range(1, 7)]
    ents += ["select.inv_time_of_use", "switch.inv_battery_grid_charging"]
    assert adapters.guess_profile(ents, {"solarman"}, "SUN-12K-SG05LP3") == "solarman"


def _export_step(seen):
    ctl, ov = Ctl({"select.fox_work_mode": {"state": "Self Use"}}), Ov()
    ctl.profile_key = lambda part: "foxess_modbus"
    t = SelfTest(ctl, ov)
    out = []
    t._result = lambda *a, **k: out.append((a, k))
    t._save = lambda **k: None
    t._alternatives = lambda calls: []
    t._offline = lambda e: False

    async def watch(check, wait_s, base):
        return False, seen
    t._watch = watch
    calls = [{"domain": "select", "service": "select_option", "data": {"entity_id": "select.fox_work_mode", "option": "Force Discharge"}}]
    asyncio.run(t._step("battery", "export", calls, None, 1, {}))
    return out[-1]


def test_export_limited_is_not_a_fault():
    a, k = _export_step({"battery": -1500, "grid": 200, "pv": 0})
    assert a[2] == "skipped" and k["why"] == "export_limited"


def test_export_without_discharge_is_still_a_fault():
    a, k = _export_step({"battery": 0, "grid": 800, "pv": 0})
    assert a[2] == "failed" and k["why"] == "no_reaction"

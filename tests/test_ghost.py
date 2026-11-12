"""A charger in shadow: Energy Pilot's charge beside the real one."""

from datetime import datetime, timedelta

from energy_pilot.ghost import Ghosts

T0 = datetime(2026, 11, 12, 23, 0)


def test_plan_is_kept_and_real_charge_measured():
    g = Ghosts({})
    g.see("car2", T0, True, 0, 0.07, 30)
    assert g.wants_plan("car2")
    hours = [T0 + timedelta(hours=k) for k in (1, 2, 3)]
    g.set_plan("car2", hours, 10.0, {h: 0.07 for h in hours}, 3.7, 1.0)
    assert not g.wants_plan("car2")
    p = g.view()["car2"]["plan"]
    assert p["kwh"] == 10.0 and abs(p["avg"] - 0.07) < 1e-6
    for m in range(0, 120, 1):  # two hours at 3.7 kW, minute by minute
        g.see("car2", T0 + timedelta(minutes=30 + m), True, 3700, 0.08, 60)
    own = g.view()["car2"]["own"]
    assert abs(own["kwh"] - 7.4) < 0.1 and abs(own["avg"] - 0.08) < 1e-3 and own["first"].startswith("2026-11-12T23:30")
    assert g.view()["car2"]["plan"]["kwh"] == 10.0   # the plan doesn't shrink as the car fills


def test_unplug_keeps_the_last_and_learns_the_need():
    g = Ghosts({})
    for night, kwh in enumerate((18, 20, 22)):
        t = T0 + timedelta(days=night)
        g.see("car", t, True, 0, 0.1, 30)
        g.see("car", t + timedelta(minutes=1), True, kwh * 1000, 0.1, 3600)
        g.see("car", t + timedelta(hours=8), False, 0, 0.1, 30)
    v = g.view()["car"]
    assert v["last"]["own"]["kwh"] == 22 and v["plan"] is None
    assert g.need("car", 5) == 20

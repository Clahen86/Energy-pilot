from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from energy_pilot.battstats import BattStats
from energy_pilot.runtime import evening, next_action

TZ = ZoneInfo("Europe/Copenhagen")


def test_longest_off_grid_and_evening_streak(tmp_path):
    b = BattStats(tmp_path)
    t = datetime(2026, 11, 14, 16, 0, tzinfo=TZ)
    for i in range(int(7 * 120)):  # 7 hours, every half minute, buying nothing
        b.tick(t + timedelta(seconds=30 * i), {"soc": 80, "grid": 10}, 10)
    s = b.summary(t + timedelta(hours=7), 10)
    assert s["best"]["h"] >= 6.9 and s["streak"] == 1


def test_a_kettle_blip_does_not_end_the_run(tmp_path):
    b = BattStats(tmp_path)
    t = datetime(2026, 11, 14, 10, 0, tzinfo=TZ)
    for i in range(240):
        b.tick(t + timedelta(seconds=30 * i), {"soc": 60, "grid": 2000 if 100 <= i < 103 else 0}, 10)
    assert b.state["best"]["h"] > 1.9


def test_next_action_and_evening():
    now = datetime(2026, 11, 15, 9, 10, tzinfo=TZ)
    steps = [{"t": (now.replace(minute=0) + timedelta(hours=i)).isoformat(), "action": a, "soc": s}
             for i, (a, s) in enumerate([("charge_grid", 40), ("charge_grid", 60), ("hold", 60), ("discharge", 50)])]
    n = next_action(steps, now)
    assert n["do"] == "charge" and n["soc"] == 60 and n["then"] == "hold" and n["to"].startswith("2026-11-15T11:00")
    curve = [{"t": (now.replace(minute=0) + timedelta(hours=i)).isoformat(), "soc": 90, "price": 3 if 8 <= i < 12 else 1,
              "house": 1.5, "sun": 0} for i in range(20)]
    e = evening(curve, 50, 10, 10)
    assert e["need"] == 6.0 and e["have"] == 8.0 and e["ok"]


def test_next_action_with_quarter_slots():
    now = datetime(2026, 11, 15, 10, 5, tzinfo=TZ)
    t = now.replace(minute=0)
    steps = [{"t": (t + timedelta(minutes=15 * i)).isoformat(), "action": a, "soc": 30 + i} for i, a in enumerate(["hold", "charge_grid", "charge_grid", "hold"])]
    n = next_action(steps, now)
    assert n["do"] == "hold" and n["to"].startswith("2026-11-15T10:15") and n["then"] == "charge"

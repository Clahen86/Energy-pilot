"""The last two days, every 5 minutes - kept over a restart and sent with a report."""

from types import SimpleNamespace
import time

from energy_pilot.timeline import KEEP, Timeline, snapshot


def test_kept_over_a_restart_and_only_two_days(tmp_path):
    p = tmp_path / "tl.jsonl"
    t = Timeline(p)
    now = time.time()
    for i in range(KEEP + 10):
        t.add({"t": int(now - (KEEP + 10 - i) * 300), "soc": i})
    t.save()
    again = Timeline(p)
    assert len(again.rows) == KEEP and again.rows[-1]["soc"] == KEEP + 9
    assert all(r["t"] >= now - 48 * 3600 for r in again.last())


def test_snapshot_has_the_flows_the_plan_and_what_each_part_was_told():
    ov = SimpleNamespace(flow=lambda: {"pv": 0.0, "house": 4200.0, "battery": 10400.0, "soc": 62.0, "grid": 1600.0, "ev": 7800.0, "plug": True})
    eng = SimpleNamespace(result={"battery": {"now": "discharge", "target": 40.0}, "car": {"hours": []}},
                          now_slot={"price": 0.42, "sun_f": 0.0, "house_f": 1.1})
    ctl = SimpleNamespace(intents=lambda: {"battery": {"intent": "normal"}, "car": {"intent": "stop"}},
                          mode=lambda p: "control" if p == "battery" else "shadow", car_why="waiting")
    r = snapshot(ov, eng, ctl)
    assert r["ev"] == 7800.0 and r["price"] == 0.42 and r["plan"] == "discharge"
    assert r["do"] == {"battery": ["control", "normal"], "car": ["shadow", "stop"]} and r["car_why"] == "waiting"
    assert snapshot(ov, None, None)["soc"] == 62.0  # no engine yet: just the flows

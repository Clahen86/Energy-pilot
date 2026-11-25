"""A battery read in the wrong unit (W taken as kW) must not become a saving of thousands."""
from datetime import datetime, timedelta
import json

from energy_pilot.ledger import Ledger


def test_impossible_battery_reading_is_not_counted(tmp_path):
    led = Ledger(tmp_path)
    t = datetime(2026, 11, 20, 18, 0)
    flow = {"battery": -858_000.0, "pv": 0.0, "house": 800.0, "ev": 0.0, "soc": 60.0, "grid": 0.0}
    for i in range(20):
        led.tick(t + timedelta(seconds=30 * i), flow, 0.27, 0.2, 35.0, 10.0, 0.9, max_charge_kw=8, max_discharge_kw=5.2)
    assert abs(led.state["days"].get("2026-11-20", {}).get("saved", 0.0)) < 1


def test_old_wrong_day_is_repaired_once(tmp_path):
    days = {f"2026-11-{d:02d}": {"saved": 2.5, "all": 3.0, "cost": 1.0, "without": 3.5, "bought": 5, "sold": 1} for d in range(10, 20)}
    days["2026-11-20"] = {"saved": 6050.0, "all": 6051.0, "cost": 1.0, "without": 6051.0, "bought": 5, "sold": 1}
    (tmp_path / "energy_pilot_ledger.json").write_text(json.dumps({"stored_kwh": 0, "stored_cost": 0, "since": "2026-11-10", "days": days}))
    led = Ledger(tmp_path)
    assert led.state["days"]["2026-11-20"]["saved"] == 0.0
    assert led.state["days"]["2026-11-15"]["saved"] == 2.5

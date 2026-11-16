import json
from datetime import datetime
from types import SimpleNamespace

from energy_pilot.learning import Learning, accuracy


def test_accuracy():
    rows = [{"h": h, "house": [1.0, 1.0 if h % 2 else 1.2], "sun": [None, None], "soc": [50, 52]} for h in range(24)]
    a = accuracy(rows)
    assert a["house"] == 91  # 2.4 kWh off of 26.4
    assert a["sun"] is None
    assert a["soc"] == 98


def test_expected_merges_battery_rows(tmp_path):
    L = Learning.__new__(Learning)
    L.log_file = tmp_path / "exp.jsonl"
    L.log_file.write_text("\n".join(json.dumps(r) for r in [
        {"t": "2026-11-15T10:00:00+01:00", "house": 0.5, "sun": 1.0},
        {"t": "2026-11-15T10:00:00+01:00", "soc_plan": 40},
        {"t": "2026-11-15T10:05:00+01:00", "house": 0.9, "soc_plan": 44},
    ]))
    e = L._expected("2026-11-15")["2026-11-15T10"]
    assert e["house"] == 0.5 and e["soc_plan"] == 40

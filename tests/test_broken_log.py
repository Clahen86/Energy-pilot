"""A broken line in the expectations log (zeros after a power cut) is skipped - it once hid every plan after it."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from energy_pilot.learning import Learning
from energy_pilot.timeline import Timeline


def test_plans_after_a_broken_line_are_still_read_and_the_log_is_trimmed(tmp_path):
    lg = Learning(tmp_path)
    old = json.dumps({"t": "2026-11-01T10:00:00+01:00", "house": 1.0})
    before = json.dumps({"t": "2026-11-20T10:00:00+01:00", "house": 0.8})
    after = json.dumps({"t": "2026-11-21T10:00:00+01:00", "house": 1.2, "soc_plan": 40})
    lg.log_file.write_text("\n".join([old, before, "\x00" * 200, after]) + "\n")
    assert lg._expected("2026-11-21")["2026-11-21T10"]["house"] == 1.2
    lg._trim(datetime(2026, 11, 22, tzinfo=ZoneInfo("Europe/Copenhagen")))
    kept = lg.log_file.read_text().splitlines()
    assert len(kept) == 2 and "\x00" not in lg.log_file.read_text()  # 14 days kept, the zeros gone


def test_timeline_keeps_the_rows_around_a_broken_line(tmp_path):
    p = tmp_path / "tl.jsonl"
    p.write_text('{"t": 1, "soc": 5}\n' + "\x00" * 50 + '\n{"t": 2, "soc": 6}\n')
    assert [r["soc"] for r in Timeline(p).rows] == [5, 6]

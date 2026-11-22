"""What if: the last days replayed with a bigger battery or more panels."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from energy_pilot.engine import Battery
from energy_pilot.whatif import Hourly, compute

TZ = ZoneInfo("Europe/Copenhagen")


def _fill(h, days=8):
    t0 = datetime(2026, 11, 1, 0, tzinfo=TZ)
    for d in range(days):
        for hr in range(24):
            now = t0 + timedelta(days=d, hours=hr)
            price = 3.0 if 17 <= hr < 21 else 1.0
            sun = 4000 if 10 <= hr < 15 else 0
            for _ in range(3):
                h.add(now, 1200 if 17 <= hr < 22 else 500, sun, price, 0.3)


def test_hours_kept_and_whole_days_only(tmp_path):
    h = Hourly(tmp_path / "h.json")
    _fill(h)
    h.save()
    again = Hourly(tmp_path / "h.json")
    assert len(again.days("2026-11-09")) == 8 and len(again.days("2026-11-05")) == 4
    r = again.h["2026-11-01T18"]
    assert r["house"] == 1.2 and r["price"] == 3.0


def test_bigger_battery_and_more_sun_cost_less_and_none_costs_more(tmp_path):
    h = Hourly(tmp_path / "h.json")
    _fill(h)
    b = Battery(capacity_kwh=5, max_charge_kw=3, max_discharge_kw=3, min_soc=10, grid_charge=True)
    w = compute(h.days("2026-11-09"), b, TZ)
    assert w["days"] == 8
    assert w["bigger"] <= w["now"] and w["sun"] < w["now"] < w["none"]
    assert compute(h.days("2026-11-04"), b, TZ) is None  # not 7 days yet

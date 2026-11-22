"""US rates: URDB tariffs become schedule deals (tier 1, hourly rules per month, fixed charge a month)."""

import asyncio

from energy_pilot import us_rates

NOW = 1_790_000_000  # 2026-09
FLAT_GRID = [[0] * 24 for _ in range(12)]
SUMMER = [5, 6, 7, 8, 9]  # June-October (0-based)
# Weekdays: summer peak 16-21 (period 1), else period 0; summer weekends period 2 all day.
WD = [[1 if m in SUMMER and 16 <= h < 21 else 0 for h in range(24)] for m in range(12)]
WE = [[2 if m in SUMMER else 0] * 24 for m in range(12)]


def item(label, name, start, end=None, **kw):
    base = {"label": label, "name": name, "utility": "Test Electric Co", "startdate": start, "sector": "Residential",
            "fixedchargefirstmeter": 10, "fixedchargeunits": "$/month",
            "energyratestructure": [[{"max": 500, "rate": 0.10, "adj": 0.02, "unit": "kWh"}, {"rate": 0.20, "unit": "kWh"}]],
            "energyweekdayschedule": FLAT_GRID, "energyweekendschedule": FLAT_GRID}
    if end is not None:
        base["enddate"] = end
    base.update(kw)
    return base


def price(deal, month, weekday, hour):
    """The engine's rule: the period for the month, then the first rule that matches day and minute."""
    per = next(p for p in deal["periods"] if p["from"] <= f"{month:02d}-15" <= p["to"])
    m = hour * 60
    return next(r["rate"] for r in per["rules"] if (r["days"] is None or weekday in r["days"]) and r["from"] <= m < r["to"])


ITEMS = [
    item("flat1", "Residential", NOW - 10_000),
    item("flat0", "Residential", NOW - 90_000_000),  # older revision, still open-ended: the newer one wins
    item("tou1", "Residential TOU", NOW - 10_000, fixedchargefirstmeter=0.5, fixedchargeunits="$/day",
         energyratestructure=[[{"rate": 0.08, "unit": "kWh", "sellrate": 0.03}], [{"rate": 0.30, "adj": 0.05, "unit": "kWh"}],
                              [{"rate": 0.12, "unit": "kWh"}]],
         energyweekdayschedule=WD, energyweekendschedule=WE),
    item("old1", "Residential Legacy", NOW - 90_000_000, NOW - 1000),  # expired
]


def test_schema_and_filtering():
    deals = us_rates.parse(ITEMS, now=NOW)
    assert sorted(d["id"] for d in deals) == ["us:flat1", "us:tou1"]
    for d in deals:
        assert set(d) == {"id", "name", "supplier", "url", "monthly", "fit", "partial", "periods"}
        assert d["partial"] is False and d["supplier"] == "Test Electric Co"
        assert d["url"] == "https://apps.openei.org/USURDB/rate/view/" + d["id"][3:]
        assert len(d["periods"]) == 12 and d["periods"][0]["from"] == "01-01" and d["periods"][11]["to"] == "12-31"


def test_flat_tier1_with_adj():
    flat = next(d for d in us_rates.parse(ITEMS, now=NOW) if d["id"] == "us:flat1")
    assert flat["monthly"] == 10 and flat["fit"] is None
    # Merged into one rule a day type: tier 1 rate + adj, the 0.20 tier ignored.
    assert flat["periods"][3]["rules"] == [{"days": [0, 1, 2, 3, 4], "from": 0, "to": 1440, "rate": 0.12},
                                           {"days": [5, 6], "from": 0, "to": 1440, "rate": 0.12}]


def test_tou_summer_winter_weekday_weekend():
    tou = next(d for d in us_rates.parse(ITEMS, now=NOW) if d["id"] == "us:tou1")
    assert abs(tou["monthly"] - 0.5 * 365.25 / 12) < 1e-3  # $/day -> a month
    assert tou["fit"] == 0.03
    assert price(tou, 7, 2, 17) == 0.35  # July weekday 17:00: peak incl. adj
    assert price(tou, 7, 2, 10) == 0.08
    assert price(tou, 7, 6, 17) == 0.12  # July Sunday: weekend rate
    assert price(tou, 1, 2, 17) == 0.08  # January: no peak
    assert len(tou["periods"][6]["rules"]) == 4  # off-peak, peak, off-peak, weekend


def test_fetch_never_raises():
    class Boom:
        def get(self, *a, **k):
            raise RuntimeError("no network")

    assert asyncio.run(us_rates.fetch(Boom(), 37.7749, -122.4194)) == []

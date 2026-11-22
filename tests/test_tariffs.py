"""Which electricity deal would have been cheapest - each with its own battery plan."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from energy_pilot.engine import Battery
from energy_pilot.tariffs import _hourly, compare, dk_offers
from energy_pilot.whatif import Hourly

TZ = ZoneInfo("Europe/Copenhagen")
ELPRIS = {"products": [
    {"productId": 1, "name": "Spot billig", "private1": True, "supplier": {"name": "A"}, "orderUrl": "https://a",
     "productPrices": [{"subscription": 20.0, "additionalNordPoolSpot": True, "validFrom": "2026-01-01", "validTo": "2027-12-31",
                        "matrix": [{"hoursFrom": 0, "hoursTo": 24, "volumeFrom": 0, "amount": 2.0}]}]},
    {"productId": 2, "name": "Spot dyr", "private1": True, "supplier": {"name": "B"},
     "productPrices": [{"subscription": 0.0, "additionalNordPoolSpot": True, "validFrom": "2026-01-01",
                        "matrix": [{"hoursFrom": 0, "hoursTo": 24, "volumeFrom": 0, "amount": 30.0}]}]},
    {"productId": 3, "name": "Fast", "private1": True, "supplier": {"name": "C"},
     "productPrices": [{"subscription": 10.0, "additionalNordPoolSpot": False, "validFrom": "2026-01-01",
                        "matrix": [{"hoursFrom": 0, "hoursTo": 24, "volumeFrom": 0, "amount": 150.0}]}]},
    {"productId": 4, "name": "Erhverv", "private1": False, "supplier": {"name": "D"}, "productPrices": []},
]}


def _history(tmp_path, days=8):
    h = Hourly(tmp_path / "h.json")
    spot = {}
    t0 = datetime(2026, 11, 1, 0, tzinfo=TZ)
    for d in range(days):
        for hr in range(24):
            t = t0 + timedelta(days=d, hours=hr)
            s = 1.5 if 17 <= hr < 21 else 0.4  # spot DKK/kWh excl. VAT
            spot[t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H")] = s
            total = 1.2 + s * 1.25 + 0.025  # grid + taxes, spot, deal A's markup
            for _ in range(3):
                h.add(t, 1500 if 17 <= hr < 22 else 400, 3000 if 10 <= hr < 15 else 0, total, 0.3)
    return h, spot


def test_reads_the_private_deals_incl_vat():
    offers = dk_offers(ELPRIS, "2026-11-22")
    assert [o["name"] for o in offers] == ["Spot billig", "Spot dyr", "Fast"]
    assert offers[0]["parts"] == [(0, 24, 0.025)] and offers[0]["monthly"] == 25.0 and offers[0]["spot"]
    assert offers[2]["kind"] == "fixed" and offers[2]["parts"][0][2] == 1.875


def test_cheapest_deal_found_and_own_deal_shown(tmp_path):
    h, spot = _history(tmp_path)
    b = Battery(capacity_kwh=10, max_charge_kw=5, max_discharge_kw=5, min_soc=10, grid_charge=True)
    r = compare(h.days("2026-11-09"), b, TZ, dk_offers(ELPRIS, "2026-11-22"), spot, "dk:2-0")
    assert r["mode"] == "deals" and r["count"] == 3
    assert r["best"][0]["name"] == "Spot billig"  # the small markup wins, also with its monthly fee
    assert r["current"]["name"] == "Spot dyr" and r["current"]["cost"] > r["best"][0]["cost"]


def test_no_public_deals_compares_hourly_with_fixed(tmp_path):
    h, _ = _history(tmp_path)
    b = Battery(capacity_kwh=10, max_charge_kw=5, max_discharge_kw=5, min_soc=10, grid_charge=True)
    r = compare(h.days("2026-11-09"), b, TZ, [], {}, None)
    assert r["mode"] == "flat" and r["hourly"] < r["fixed"]  # with a battery the hourly price pays here
    assert compare(h.days("2026-11-05"), b, TZ, [], {}, None) is None  # not 7 days yet


def test_uk_octopus_deals_each_planned(tmp_path):
    h, _ = _history(tmp_path)
    rates_agile, rates_flex = {}, {}
    t0 = datetime(2026, 11, 1, 0, tzinfo=TZ)
    for i in range(8 * 48):
        t = (t0 + timedelta(minutes=30 * i)).astimezone(timezone.utc)
        k = t.strftime("%Y-%m-%dT%H:%M")
        rates_agile[k] = 0.35 if 16 <= t.hour < 19 else 0.12
        rates_flex[k] = 0.24
    uk = {"AGILE-X": {"name": "Agile Octopus", "rates": _hourly(rates_agile), "standing": 0.5},
          "VAR-X": {"name": "Flexible Octopus", "rates": _hourly(rates_flex), "standing": 0.5}}
    b = Battery(capacity_kwh=10, max_charge_kw=5, max_discharge_kw=5, min_soc=10, grid_charge=True)
    r = compare(h.days("2026-11-09"), b, TZ, [], {}, "VAR-X", uk)
    assert r["best"][0]["name"] == "Agile Octopus" and r["current"]["name"] == "Flexible Octopus"


def test_time_of_use_deals_each_planned_and_own_shown(tmp_path):
    h, _ = _history(tmp_path)
    flat = {"id": "au:flat", "name": "Flat", "supplier": "R1", "monthly": 30.0, "fit": 0.05, "partial": False,
            "periods": [{"from": "01-01", "to": "12-31", "rules": [{"days": None, "from": 0, "to": 1440, "rate": 0.30}]}]}
    tou = {"id": "au:tou", "name": "TOU", "supplier": "R2", "monthly": 30.0, "fit": 0.05, "partial": False,
           "periods": [{"from": "01-01", "to": "12-31", "rules": [{"days": None, "from": 15 * 60, "to": 21 * 60, "rate": 0.45},
                                                                  {"days": None, "from": 0, "to": 1440, "rate": 0.15}]}]}
    b = Battery(capacity_kwh=10, max_charge_kw=5, max_discharge_kw=5, min_soc=10, grid_charge=True)
    r = compare(h.days("2026-11-09"), b, TZ, [], {}, "au:flat", None, [flat, tou])
    assert r["best"][0]["id"] == "au:tou" and r["current"]["id"] == "au:flat" and r["count"] == 2

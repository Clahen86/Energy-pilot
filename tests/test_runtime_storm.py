"""How long the battery lasts, and the storm watch: full before the storm (in the cheap hours), kept high during it."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from energy_pilot import runtime, storm
from energy_pilot.engine import Battery, Hour, plan_battery

T0 = datetime(2026, 11, 15, 20, 0, tzinfo=timezone.utc)


def _plan(house=1.0, sun=0.0, n=24, soc=None):
    return {"hours": [{"t": (T0 + timedelta(hours=i)).isoformat(), "house": house, "sun": sun, "soc": (soc[i] if soc else 50), "charge": bool(soc and i in (6, 7))}
                      for i in range(n)]}


def test_lasts_until():
    # 10 kWh, 60 % now, 10 % lowest: 5 kWh at 1 kW = 5 hours
    r = runtime.compute(_plan(), {"soc": 60, "house": 1000}, 10, 10, T0)
    assert datetime.fromisoformat(r["until"]) == T0 + timedelta(hours=5)
    assert r["kwh"] == 6.0 and round(r["hours"], 1) == 5.0


def test_sun_lasts_beyond():
    r = runtime.compute(_plan(house=0.5, sun=1.0), {"soc": 50, "house": 500}, 10, 10, T0)
    assert r["until"] is None and r["beyond"]


def test_low_full_cheap_from_the_plan():
    socs = [60, 50, 40, 30, 25, 20, 40, 70, 96] + [96] * 15
    r = runtime.compute(_plan(soc=socs), {"soc": 60, "house": 1000}, 10, 10, T0)
    assert r["low"]["soc"] == 20 and r["full"] == (T0 + timedelta(hours=8)).isoformat()
    assert r["cheap"] == {"from": (T0 + timedelta(hours=6)).isoformat(), "to": (T0 + timedelta(hours=8)).isoformat()}


def test_storm_found_in_the_forecast():
    w = SimpleNamespace(hours={T0 + timedelta(hours=i): {"gust": 100 if 10 <= i <= 13 else 30, "code": 3} for i in range(40)})
    st = storm.find(w, T0, {"storm_gust": 25})
    assert st["from"] == (T0 + timedelta(hours=10)).isoformat() and st["to"] == (T0 + timedelta(hours=14)).isoformat()
    assert st["kind"] == "wind" and st["gust"] == 27.8
    assert storm.find(w, T0, {"storm_gust": 30}) is None


def test_thunder_and_warning():
    w = SimpleNamespace(hours={T0 + timedelta(hours=3): {"gust": 20, "code": 95}})
    assert storm.find(w, T0, {})["kind"] == "thunder"
    states = {"binary_sensor.meteoalarm": {"state": "on", "attributes": {"awareness_level": "3; orange; Severe", "event": "Wind warning"}}}
    assert storm.find(SimpleNamespace(hours={}), T0, {}, states)["kind"] == "warning"


def test_storm_fills_in_the_cheap_hours_and_holds():
    st = {"from": (T0 + timedelta(hours=8)).isoformat(), "to": (T0 + timedelta(hours=11)).isoformat()}
    at = storm.targets(st, {})
    assert at[0] == (T0 + timedelta(hours=8), 100.0) and all(s == 80.0 for _t, s in at[1:])
    prices = [2.0, 2.0, 0.5, 0.5, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0]
    hours = [Hour(T0 + timedelta(hours=i), p, 0.0, 0.5, 0.0) for i, p in enumerate(prices)]
    b = Battery(capacity_kwh=10, max_charge_kw=5, max_discharge_kw=5, min_soc=10, grid_max_soc=100, efficiency=1.0, at=at)
    p = plan_battery(hours, 30, b)
    assert p.steps[7].soc_end >= 99  # full when the storm comes
    assert all(s.soc_end >= 79 for s in p.steps[8:11])  # kept high during it
    charged = [i for i, s in enumerate(p.steps) if s.action == "charge_grid"]
    assert 2 in charged and 3 in charged  # the cheap hours are used

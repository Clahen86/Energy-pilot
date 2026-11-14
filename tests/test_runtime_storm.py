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


def _w(states, reg=None):
    return storm._warning(states, reg)


def test_warnings_from_the_weather_services():
    # Meteoalarm (Europe): orange wind - yes; yellow - no
    assert _w({"binary_sensor.meteoalarm": {"state": "on", "attributes": {"awareness_level": "3; orange; Severe", "awareness_type": "1; Wind", "event": "Orange wind warning"}}})
    assert not _w({"binary_sensor.meteoalarm": {"state": "on", "attributes": {"awareness_level": "2; yellow; Moderate", "awareness_type": "1; Wind"}}})
    # DWD (DE): level 3, storm
    dwd = {"sensor.berlin_current_warning_level": {"state": "3", "attributes": {"warning_1_name": "ORKANARTIGE BÖEN", "warning_1_type": 1}}}
    assert _w(dwd, {"sensor.berlin_current_warning_level": {"platform": "dwd_weather_warnings"}})["source"] == "dwd_weather_warnings"
    assert not _w({"sensor.berlin_current_warning_level": {"state": "1", "attributes": {"warning_1_name": "WINDBÖEN", "warning_1_type": 1}}})
    # Météo-France: Vent violent orange
    assert _w({"sensor.29_weather_alert": {"state": "Orange", "attributes": {"Vent violent": "Orange", "Pluie-inondation": "Vert"}}})
    assert not _w({"sensor.29_weather_alert": {"state": "Jaune", "attributes": {"Vent violent": "Jaune"}}})
    # NWS Alerts (US)
    assert _w({"sensor.nws_alerts": {"state": "1", "attributes": {"Alerts": [{"Event": "High Wind Warning", "Severity": "Severe", "Onset": "2026-11-16T03:00:00-05:00"}]}}})
    assert not _w({"sensor.nws_alerts": {"state": "1", "attributes": {"Alerts": [{"Event": "Wind Advisory", "Severity": "Minor"}]}}})
    # BOM (AU), Environment Canada, MET (NO)
    assert _w({"sensor.sydney_warnings": {"state": "1", "attributes": {"warnings": [{"short_title": "Severe Thunderstorm Warning", "warning_group_type": "major"}]}}})
    assert _w({"sensor.ottawa_warnings": {"state": "1", "attributes": {"alert_1": "Wind warning in effect"}}}, {"sensor.ottawa_warnings": {"platform": "environment_canada"}})
    assert _w({"sensor.met_alerts": {"state": "3", "attributes": {"awareness_level": "3; orange; Moderate", "event": "Kuling", "title": "Kraftige vindkast"}}})
    # GDACS (the whole world): a red cyclone 250 km away
    assert _w({"geo_location.cyclone_x": {"state": "250", "attributes": {"event_type": "Tropical Cyclone", "alert_level": "Red"}}}, {"geo_location.cyclone_x": {"platform": "gdacs"}})
    assert not _w({"geo_location.cyclone_x": {"state": "2500", "attributes": {"event_type": "Tropical Cyclone", "alert_level": "Red"}}}, {"geo_location.cyclone_x": {"platform": "gdacs"}})
    # never a sensor that isn't a warning
    assert not _w({"sensor.wind_speed": {"state": "30", "attributes": {"unit_of_measurement": "m/s"}}})


def test_warning_starts_when_it_says():
    states = {"sensor.nws_alerts": {"state": "1", "attributes": {"Alerts": [{"Event": "Hurricane Warning", "Onset": (T0 + timedelta(hours=6)).isoformat()}]}}}
    st = storm.find(SimpleNamespace(hours={}), T0, {}, states)
    assert st["kind"] == "warning" and datetime.fromisoformat(st["from"]) == T0 + timedelta(hours=6)


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

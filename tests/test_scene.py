"""The flow card's dress: each country its own holidays, the seasons by hemisphere."""

from datetime import date, datetime

from energy_pilot.scene import build, holiday, season


def key(c, d):
    h = holiday(c, date.fromisoformat(d))
    return h and h["key"]


def test_denmark_through_the_year():
    assert key("DK", "2026-11-28") is None and key("DK", "2026-11-29") == "jul"  # the first Sunday in Advent
    assert key("DK", "2026-12-26") == "jul" and key("DK", "2026-12-27") is None
    assert key("DK", "2026-12-31") == "nytaar" and key("DK", "2027-01-01") == "nytaar"
    assert key("DK", "2026-02-15") == "carnival"  # Fastelavn
    assert key("DK", "2026-03-29") == "paaske" and key("DK", "2026-04-06") == "paaske" and key("DK", "2026-04-07") is None
    assert key("DK", "2026-06-05") == "national" and key("DK", "2026-06-23") == "midsummer" and key("DK", "2026-10-30") == "halloween"


def test_other_countries_keep_their_own():
    assert key("NO", "2026-05-17") == "national" and key("US", "2026-07-04") == "national"
    assert key("US", "2026-11-26") == "thanksgiving" and key("CA", "2026-10-12") == "thanksgiving"
    assert key("GB", "2026-11-05") == "bonfire" and key("GB", "2026-06-05") is None
    assert key("SE", "2026-06-19") == "midsummer" and key("FI", "2026-06-19") == "midsummer"
    assert key("CN", "2027-02-06") == "lunar" and key("CN", "2026-12-24") is None  # no Christmas there
    assert key("IN", "2026-11-08") == "diwali" and key("SA", "2026-03-20") == "eid"
    assert key("GR", "2026-04-12") == "paaske"  # Orthodox Easter, a week after the western one
    assert key("JP", "2026-12-24") is None and key("XX", "2026-12-24") == "jul"  # unknown country: the common days


def test_seasons_follow_the_hemisphere():
    d = date(2026, 12, 24)
    assert season(d, 55.7) == "winter" and season(d, -33.9) == "summer" and season(d, 1.3) is None


def test_build_from_home_assistant():
    states = {"sun.sun": {"attributes": {"elevation": -20}},
              "weather.home": {"state": "snowy", "attributes": {"temperature": 30.2, "temperature_unit": "°F", "wind_speed": 36, "wind_speed_unit": "km/h"}}}
    s = build(states, {"country": "DK", "latitude": 55.7}, datetime(2026, 12, 20, 18))
    assert s["condition"] == "snowy" and s["wind"] == 10.0 and round(s["outdoor"]) == -1
    assert s["season"] == "winter" and s["holiday"]["key"] == "jul"
    assert build({}, {}, datetime(2026, 7, 1))["holiday"] is None  # nothing known: nothing breaks

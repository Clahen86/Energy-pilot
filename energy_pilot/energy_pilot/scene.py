"""What the flow card is dressed in: the time of day, the real weather, the season and the day's holiday - by country.

The holidays are the ones the country keeps (the holidays library gives the moving dates: Easter, Eid, Chinese New
Year, Diwali, Midsummer), each drawn in the card's own language: a ring of lights around the house in the holiday's
colours, or a few particles (fireworks, confetti, embers). A country not listed gets the weather and the season only.
The seasons follow the hemisphere (summer in December south of the equator) and stay away near the equator.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache
import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)

# where Christmas and Easter are kept (the rest of the world gets New Year and its own days)
NO_CHRISTMAS = {"IL", "SA", "AE", "QA", "KW", "OM", "BH", "IR", "IQ", "AF", "PK", "YE", "TR", "EG", "DZ", "MA", "TN", "LY",
                "JO", "SY", "LB", "ID", "MY", "BD", "CN", "IN", "NP", "TH", "VN", "KH", "LA", "MM", "MN", "JP", "KR", "TW"}
ORTHODOX = {"GR", "CY", "RU", "UA", "BY", "RO", "BG", "RS", "ME", "MK", "GE", "MD"}
CARNIVAL = {"DK", "NO", "SE", "DE", "AT", "CH", "NL", "BE", "LU", "FR", "IT", "ES", "PT", "BR", "AR", "UY", "CO", "MX", "HR", "SI"}
HALLOWEEN = {"US", "CA", "GB", "IE", "AU", "NZ", "DK", "NO", "SE", "NL", "DE", "BE"}
MIDSUMMER = {"DK": "23-06", "NO": "23-06", "EE": "23-06", "LV": "23-06", "LT": "23-06"}  # SE and FI: the library's Midsummer Eve
# national days: (day-month, colours of the flag)
NATIONAL = {
    "DK": ("05-06", ["#c8102e", "#ffffff"]), "NO": ("17-05", ["#ba0c2f", "#ffffff", "#00205b"]), "SE": ("06-06", ["#006aa7", "#fecc00"]),
    "FI": ("06-12", ["#002f6c", "#ffffff"]), "US": ("04-07", ["#b22234", "#ffffff", "#3c3b6e"]), "FR": ("14-07", ["#0055a4", "#ffffff", "#ef4135"]),
    "NL": ("27-04", ["#ff7f00", "#ffa62e"]), "DE": ("03-10", ["#000000", "#dd0000", "#ffce00"]), "CA": ("01-07", ["#d52b1e", "#ffffff"]),
    "IE": ("17-03", ["#169b62", "#ffffff", "#ff883e"]), "CH": ("01-08", ["#d52b1e", "#ffffff"]), "BE": ("21-07", ["#000000", "#fdda24", "#ef3340"]),
    "IT": ("02-06", ["#009246", "#ffffff", "#ce2b37"]), "ES": ("12-10", ["#aa151b", "#f1bf00"]), "PL": ("03-05", ["#ffffff", "#dc143c"]),
    "AT": ("26-10", ["#ed2939", "#ffffff"]), "PT": ("10-06", ["#006600", "#ff0000"]), "IS": ("17-06", ["#02529c", "#ffffff", "#dc1e35"]),
}
LUNAR = {"CN", "TW", "HK", "MO", "SG", "VN", "KR", "MY"}
DIWALI = {"IN", "NP", "SG", "MY", "LK", "MU", "FJ"}
EID = {"SA", "AE", "QA", "KW", "OM", "BH", "TR", "EG", "ID", "MY", "PK", "BD", "MA", "DZ", "TN", "JO", "IQ", "IR", "SN", "NG"}

COLOURS = {
    "jul": ["#ff4d5e", "#ffd34d", "#3ddc84", "#4dc3ff"], "paaske": ["#ffb3cf", "#ffe680", "#a8e6a1", "#9fd0ff"],
    "halloween": ["#ff8a2a", "#9b5de5"], "thanksgiving": ["#e8892c", "#c4542a", "#f0b04a"], "lunar": ["#e0262a", "#ffd34d"],
    "diwali": ["#ffb02e", "#ff7a2a", "#ffe08a"], "eid": ["#1f9e5a", "#ffd34d"],
}


@lru_cache(maxsize=32)
def _hol(country: str, year: int) -> dict[date, str]:
    try:
        import holidays

        return dict(holidays.country_holidays(country, years=year, language="en_US"))
    except Exception:  # noqa: BLE001 - a country the library doesn't know, or no library: the fixed days only
        try:
            import holidays

            return dict(holidays.country_holidays(country, years=year))
        except Exception:  # noqa: BLE001
            return {}


def _named(country: str, day: date, *names: str) -> bool:
    return any(any(n.lower() in str(v).lower() for n in names) for d, v in _hol(country, day.year).items() if d == day)


def _near(country: str, day: date, before: int, after: int, *names: str) -> bool:
    """A holiday of that name within some days of today (Eid lasts three days, Chinese New Year starts the eve before)."""
    found = set()
    for y in {day.year - 1, day.year, day.year + 1}:
        for d, v in _hol(country, y).items():
            if any(n.lower() in str(v).lower() for n in names):
                found.add(d)
    return any(d - timedelta(days=before) <= day <= d + timedelta(days=after) for d in found)

def holiday(country: str | None, today: date) -> dict[str, Any] | None:
    """The day's holiday where the home is: {"key", "colours"} - None on an ordinary day."""
    c = (country or "").upper()
    d, dm = today, today.strftime("%d-%m")
    from dateutil.easter import EASTER_ORTHODOX, EASTER_WESTERN, easter

    if (d.month, d.day) in ((12, 31), (1, 1)):
        return {"key": "nytaar", "colours": ["#ff5d8f", "#ffd84d", "#5dd6ff"]}
    if c in NATIONAL and NATIONAL[c][0] == dm:
        return {"key": "national", "colours": NATIONAL[c][1]}
    if c == "GB" and dm == "05-11":
        return {"key": "bonfire", "colours": ["#ff7a2a", "#ffd84d"]}
    if c in MIDSUMMER and MIDSUMMER[c] == dm or c in ("SE", "FI") and (_named(c, d, "Midsummer Eve") or _named(c, d + timedelta(days=1), "Midsummer Day")):
        return {"key": "midsummer", "colours": ["#ffb02e", "#ff7a2a"]}  # Sweden lists only the Day: the evening before is the feast
    if c == "US" and d.month == 11 and d.weekday() == 3 and 22 <= d.day <= 28 or c == "CA" and d.month == 10 and d.weekday() == 0 and 8 <= d.day <= 14:
        return {"key": "thanksgiving", "colours": COLOURS["thanksgiving"]}
    if c in LUNAR and _near(c, d, 1, 3, "Lunar New Year", "Chinese New Year", "Spring Festival", "Tet", "Seollal", "Korean New Year"):
        return {"key": "lunar", "colours": COLOURS["lunar"]}
    if c in DIWALI and _near(c, d, 2, 2, "Diwali", "Deepavali"):
        return {"key": "diwali", "colours": COLOURS["diwali"]}
    if c in EID and _near(c, d, 0, 2, "Eid al-Fitr", "Eid ul-Fitr", "Id-ul-Fitr", "Ramazan", "Hari Raya Puasa", "Lebaran"):
        return {"key": "eid", "colours": COLOURS["eid"]}
    if c not in NO_CHRISTMAS:
        e = easter(d.year, EASTER_ORTHODOX if c in ORTHODOX else EASTER_WESTERN)
        if c in CARNIVAL and e - timedelta(days=51) <= d <= e - timedelta(days=47):  # Fastelavn / Rosenmontag / Mardi Gras
            return {"key": "carnival", "colours": ["#ff5d8f", "#ffd84d", "#5dd6ff", "#3ddc84", "#a78bfa"]}
        if e - timedelta(days=7) <= d <= e + timedelta(days=1):
            return {"key": "paaske", "colours": COLOURS["paaske"]}
    if c in HALLOWEEN and d.month == 10 and d.day >= 24:
        return {"key": "halloween", "colours": COLOURS["halloween"]}
    if c not in NO_CHRISTMAS:
        xmas = date(d.year, 12, 25)
        advent1 = xmas - timedelta(days=(xmas.isoweekday() % 7 or 7) + 21)  # the fourth Sunday before Christmas
        if advent1 <= d <= date(d.year, 12, 26):
            return {"key": "jul", "colours": COLOURS["jul"]}
    return None


def season(today: date, lat: float | None) -> str | None:
    """spring/summer/autumn/winter where the home is - None near the equator, where there are none to speak of."""
    if lat is not None and abs(lat) < 23.5:
        return None
    m = today.month
    s = "winter" if m in (12, 1, 2) else "spring" if m in (3, 4, 5) else "summer" if m in (6, 7, 8) else "autumn"
    if lat is not None and lat < 0:
        s = {"winter": "summer", "summer": "winter", "spring": "autumn", "autumn": "spring"}[s]
    return s


def build(states: dict[str, Any], config: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Everything the card needs to dress itself, from Home Assistant's own sun, weather and location."""
    sun = (states.get("sun.sun") or {}).get("attributes") or {}
    w = next((v for e, v in sorted(states.items()) if e.startswith("weather.")), None) or {}
    a = w.get("attributes") or {}
    wind = a.get("wind_speed")
    try:
        unit = str(a.get("wind_speed_unit") or "km/h").lower()
        wind = round(float(wind) / {"km/h": 3.6, "mph": 2.237, "kn": 1.944, "ft/s": 3.281}.get(unit, 1.0), 1)
    except (TypeError, ValueError):
        wind = None
    try:
        lat = float(config.get("latitude"))
    except (TypeError, ValueError):
        lat = None
    try:
        outdoor = float(a.get("temperature"))
        if "F" in str(a.get("temperature_unit") or ""):
            outdoor = (outdoor - 32) * 5 / 9
    except (TypeError, ValueError):
        outdoor = None
    try:
        hol = holiday(config.get("country"), now.date())
    except Exception:  # noqa: BLE001 - never let decoration break the page
        _LOGGER.debug("No holiday", exc_info=True)
        hol = None
    return {"elevation": sun.get("elevation"), "condition": w.get("state"), "cloud": a.get("cloud_coverage"), "wind": wind,
            "outdoor": outdoor, "season": season(now.date(), lat), "holiday": hol}

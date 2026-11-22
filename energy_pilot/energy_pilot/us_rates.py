"""US residential electricity tariffs from the OpenEI Utility Rate Database (URDB), as schedule deals.

URDB describes a tariff as a list of energy "periods" (each a list of tiers with rate + adj in $/kWh) and two
12 x 24 grids (weekday / weekend: month x hour -> period index). We turn that into one schedule period per
calendar month with hourly rules, the shape tariffs.sched_price() already understands.

Simplifications, on purpose:
- Tier 1 only. Tiers depend on how much the house used so far in the month; our engine prices hour by hour,
  and tier 1 is what most homes pay for most of their kWh. Heavy users on steep tiers will look a bit cheaper.
- Demand charges ($/kW) are ignored, but such tariffs are kept: the energy part is still a fair comparison.
- Minimum bills, coincident/seasonal flat demand and per-meter extras are ignored.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import aiohttp

_LOG = logging.getLogger(__name__)

API = "https://api.openei.org/utility_rates"
VIEW = "https://apps.openei.org/USURDB/rate/view/"
MAX_DEALS = 60
_DAYS_A_MONTH = 365.25 / 12


def _monthly(item: dict[str, Any]) -> float:
    """The fixed charge as money a month; URDB gives it per month, per day or (rarely) per year."""
    v = item.get("fixedchargefirstmeter")
    if v is None:
        v = item.get("fixedmonthlycharge")  # older records use this field
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        return 0.0
    unit = str(item.get("fixedchargeunits") or "$/month").lower()
    if "day" in unit:
        v *= _DAYS_A_MONTH
    elif "year" in unit:
        v /= 12
    return round(v, 4)


def _tier1(period: list[dict[str, Any]]) -> tuple[float, float | None]:
    """(price, sell rate) of a period's first tier; adj is a per-kWh adder (fuel, riders) the customer pays too."""
    t = period[0] if period else {}
    rate = float(t.get("rate") or 0) + float(t.get("adj") or 0)
    sell = t.get("sellrate")
    return round(rate, 6), (float(sell) if sell is not None else None)


def _rules(hours: list[int], prices: list[float], days: list[int]) -> list[dict[str, Any]]:
    """24 period indices -> rules, merging neighbouring hours with the same price so the list stays short."""
    out: list[dict[str, Any]] = []
    for h, p in enumerate(hours):
        rate = prices[p] if 0 <= p < len(prices) else prices[0]
        if out and out[-1]["rate"] == rate and out[-1]["to"] == h * 60:
            out[-1]["to"] = (h + 1) * 60
        else:
            out.append({"days": days, "from": h * 60, "to": (h + 1) * 60, "rate": rate})
    return out


def _deal(item: dict[str, Any]) -> dict[str, Any] | None:
    ers = item.get("energyratestructure") or []
    wd, we = item.get("energyweekdayschedule"), item.get("energyweekendschedule") or item.get("energyweekdayschedule")
    if not ers or not wd or len(wd) != 12 or len(we) != 12:
        return None  # no energy prices (e.g. demand-only or incomplete record): nothing to compare on
    tiers = [_tier1(p) for p in ers]
    prices = [p for p, _ in tiers]
    sells = [s for _, s in tiers if s is not None]
    periods = []
    for m in range(12):
        if len(wd[m]) != 24 or len(we[m]) != 24:
            return None
        rules = _rules(wd[m], prices, [0, 1, 2, 3, 4]) + _rules(we[m], prices, [5, 6])
        # Only the "MM-DD" strings are compared, so "-31" is a safe end for every month.
        periods.append({"from": f"{m + 1:02d}-01", "to": f"{m + 1:02d}-31", "rules": rules})
    label = str(item.get("label") or "")
    return {
        "id": f"us:{label}",
        "name": str(item.get("name") or label),
        "supplier": str(item.get("utility") or ""),
        "url": VIEW + label if label else str(item.get("source") or ""),
        "monthly": _monthly(item),
        # One sell rate if the tariff states it; with several (TOU sell rates) the average is a fair stand-in.
        "fit": round(sum(sells) / len(sells), 6) if sells else None,
        "partial": False,  # a US utility tariff is the whole price; no separate grid charges on top
        "periods": periods,
    }


def parse(items: list[dict[str, Any]], now: float | None = None) -> list[dict[str, Any]]:
    """URDB items -> deals: only tariffs in force now, the newest revision of each, at most MAX_DEALS."""
    now = time.time() if now is None else now
    newest: dict[tuple[str, str], dict[str, Any]] = {}
    for it in items or []:
        if not isinstance(it, dict) or not it.get("label"):
            continue
        end, start = it.get("enddate"), it.get("startdate") or 0
        if end is not None and end <= now:
            continue  # expired (URDB keeps the whole history)
        if start and start > now:
            continue  # approved but not in force yet
        key = (str(it.get("utility") or ""), str(it.get("name") or ""))  # same name at two utilities = two tariffs
        if key not in newest or start > (newest[key].get("startdate") or 0):
            newest[key] = it
    out = []
    for it in sorted(newest.values(), key=lambda i: -(i.get("startdate") or 0)):
        try:
            d = _deal(it)
        except (TypeError, ValueError, IndexError, KeyError) as e:
            _LOG.info("URDB tariff %s skipped: %s", it.get("label"), e)
            continue
        if d:
            out.append(d)
        if len(out) >= MAX_DEALS:
            break
    return out


async def fetch(session: aiohttp.ClientSession, lat: float, lon: float, api_key: str = "DEMO_KEY") -> list[dict[str, Any]]:
    """Residential tariffs for a place. Never raises: a missing US price list must not stop the rest of the add-on."""
    params = {"version": "latest", "format": "json", "detail": "full", "sector": "Residential", "approved": "true",
              # Two decimals (~1 km) is enough to find the utility and does not pinpoint the house.
              "lat": f"{round(float(lat), 2):.2f}", "lon": f"{round(float(lon), 2):.2f}", "api_key": api_key}
    try:
        async with session.get(API, params=params, timeout=aiohttp.ClientTimeout(total=60)) as r:
            if r.status != 200:
                _LOG.info("URDB answered HTTP %s", r.status)
                return []
            data = await r.json(content_type=None)
        if not isinstance(data, dict) or "error" in data:
            _LOG.info("URDB error: %s", (data or {}).get("error") if isinstance(data, dict) else data)
            return []
        return parse(data.get("items") or [])
    except Exception as e:  # noqa: BLE001 - network, JSON or shape errors all mean "no US deals this time"
        _LOG.info("URDB fetch failed: %s", e)
        return []

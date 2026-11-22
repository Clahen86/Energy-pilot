"""Australia: every retailer's electricity plans from the AER's Consumer Data Right product data (the same data as
Energy Made Easy and Victorian Energy Compare) - public, no account. Filtered to the house's postcode, turned into
deals with time-of-use rules (tariffs.sched_price). Prices there are excl. GST: 10 % is added; feed-in has no GST.

The postcode comes from the house's location (rounded to about a kilometre) via OpenStreetMap's Nominatim, once.
Fetched once a week: the plan lists of all retailers, then the details of the plans for this postcode (cached by
plan and its last update). Anything that fails gives no deals - the card then compares hourly with fixed."""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)
REGISTER = "https://api.cdr.gov.au/cdr-register/v1/energy/data-holders/brands/summary"
AER = "https://cdr.energymadeeasy.gov.au/{brand}/cds-au/v1/energy/plans"
NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
GST = 1.10
DAYS = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}
MAX_PLANS = 400


def slug(brand: str) -> str:
    """The AER's path for a retailer: its name in lower case, words joined by dashes ("Red Energy" -> red-energy)."""
    return re.sub(r"[^a-z0-9]+", "-", brand.lower().replace("&", "and")).strip("-")


def _mins(text: Any) -> int | None:
    m = re.match(r"^(\d{1,2}):?(\d{2})", str(text or ""))
    if not m:
        return None
    v = int(m.group(1)) * 60 + int(m.group(2))
    return 1440 if v >= 1439 else v  # "23:59" is the end of the day


def _rate(rates: list[dict[str, Any]] | None) -> float | None:
    """The first block's price (most use one; with blocks the first is a house's usual use), incl. GST."""
    for r in rates or []:
        try:
            return round(float(r.get("unitPrice")) * GST, 5)
        except (TypeError, ValueError):
            continue
    return None


def parse(plan: dict[str, Any]) -> dict[str, Any] | None:
    """One plan's details -> a deal (tariffs.py's schedule schema), or None when it can't be priced."""
    c = plan.get("electricityContract") or {}
    periods, supply = [], []
    for tp in c.get("tariffPeriod") or []:
        rules = []
        kind = tp.get("rateBlockUType")
        if kind == "singleRate":
            if (r := _rate((tp.get("singleRate") or {}).get("rates"))) is not None:
                rules.append({"days": None, "from": 0, "to": 1440, "rate": r})
        elif kind == "timeOfUseRates":
            for tou in tp.get("timeOfUseRates") or []:
                r = _rate(tou.get("rates"))
                if r is None:
                    continue
                for w in tou.get("timeOfUse") or []:
                    days = sorted({DAYS[d] for d in (w.get("days") or []) if d in DAYS}) or None
                    f, e = _mins(w.get("startTime")), _mins(w.get("endTime"))
                    if f is None or e is None:
                        continue
                    rules.append({"days": None if days == list(range(7)) else days, "from": f, "to": e or 1440, "rate": r})
        if not rules:
            continue  # demand-only periods: not priced here
        periods.append({"from": str(tp.get("startDate") or "01-01"), "to": str(tp.get("endDate") or "12-31"), "rules": rules})
        try:
            supply.append(float(tp.get("dailySupplyCharge")) * GST)
        except (TypeError, ValueError):
            pass
    if not periods:
        return None
    fit = None
    for f in c.get("solarFeedInTariff") or []:
        if f.get("tariffUType") == "singleTariff":
            fit = _rate((f.get("singleTariff") or {}).get("rates"))
            if fit is not None:
                fit = round(fit / GST, 5)  # no GST on feed-in
                break
    return {"id": f"au:{plan.get('planId')}", "name": str(plan.get("displayName") or plan.get("planId")),
            "supplier": str(plan.get("brandName") or plan.get("brand") or ""), "url": "https://www.energymadeeasy.gov.au/",
            "monthly": round((sum(supply) / len(supply) if supply else 0.0) * 30.4, 2), "fit": fit, "partial": False,
            "periods": periods}


def for_postcode(plans: list[dict[str, Any]], postcode: str) -> list[dict[str, Any]]:
    """The residential electricity plans offered at this postcode."""
    out = []
    for p in plans:
        g = p.get("geography") or {}
        if p.get("fuelType") != "ELECTRICITY" or p.get("customerType") != "RESIDENTIAL":
            continue
        if postcode in (g.get("excludedPostcodes") or []) or postcode not in (g.get("includedPostcodes") or []):
            continue
        out.append(p)
    return out


async def postcode(s: aiohttp.ClientSession, lat: float, lon: float) -> str | None:
    params = {"format": "jsonv2", "lat": f"{lat:.2f}", "lon": f"{lon:.2f}", "zoom": "16", "addressdetails": "1"}
    async with s.get(NOMINATIM, params=params, timeout=aiohttp.ClientTimeout(total=30)) as r:
        r.raise_for_status()
        pc = ((await r.json()).get("address") or {}).get("postcode")
    return str(pc) if pc and re.match(r"^\d{4}$", str(pc)) else None


async def fetch(s: aiohttp.ClientSession, pc: str, cache: dict[str, Any]) -> list[dict[str, Any]]:
    """All retailers' plans for the postcode as deals. cache: planId -> {"at": lastUpdated, "deal": ...}. Never raises."""
    try:
        async with s.get(REGISTER, headers={"x-v": "1"}, timeout=aiohttp.ClientTimeout(total=30)) as r:
            r.raise_for_status()
            brands = sorted({b.get("brandName") for b in (await r.json()).get("data") or [] if b.get("brandName")})
        sem = asyncio.Semaphore(6)

        async def plans_of(brand: str) -> list[dict[str, Any]]:
            async with sem:
                try:
                    params = {"fuelType": "ELECTRICITY", "effective": "CURRENT", "page-size": "1000"}
                    async with s.get(AER.format(brand=slug(brand)), params=params, headers={"x-v": "1"},
                                     timeout=aiohttp.ClientTimeout(total=60)) as r:
                        if r.status != 200:
                            return []
                        return for_postcode(((await r.json()).get("data") or {}).get("plans") or [], pc)
                except Exception:  # noqa: BLE001 - one retailer missing is fine
                    return []

        found = [p for lst in await asyncio.gather(*(plans_of(b) for b in brands)) for p in lst][:MAX_PLANS]

        async def detail(p: dict[str, Any]) -> dict[str, Any] | None:
            key, at = p["planId"], p.get("lastUpdated")
            if (hit := cache.get(key)) and hit.get("at") == at:
                return hit.get("deal")
            async with sem:
                try:
                    async with s.get(f"{AER.format(brand=p.get('brand'))}/{key}", headers={"x-v": "3"},
                                     timeout=aiohttp.ClientTimeout(total=30)) as r:
                        if r.status != 200:
                            return None
                        deal = parse((await r.json()).get("data") or {})
                except Exception:  # noqa: BLE001
                    return None
            cache[key] = {"at": at, "deal": deal}
            return deal

        deals = [d for d in await asyncio.gather(*(detail(p) for p in found)) if d]
        for k in [k for k in cache if k not in {p["planId"] for p in found}]:
            cache.pop(k)
        return deals
    except Exception:  # noqa: BLE001 - no deals: the card compares hourly with fixed
        _LOGGER.info("Could not fetch Australian plans", exc_info=True)
        return []

"""Which electricity deal would have been cheapest for this house - worked out by itself on the last 30 days.

Each deal gets its own battery plan over the same hours (the battery runs differently on an hourly price than on a
fixed one), with the same house, sun and grid charges; only the supplier's part differs. Where the deals are public:
- Denmark: the Danish Utility Regulator's elpris.dk - every private deal, with its spot markup or fixed price and
  monthly fee (excl. VAT). Nearly all deals are the same across grid areas, so one area per price area is used.
- UK: Octopus Energy's public prices for the user's region (Agile, Go, Cosy, Flexible, ...).
- Australia: every retailer's plans for the postcode (au_plans.py, the AER's public product data).
- Italy: every household offer on ARERA's Portale Offerte open data (it_offers.py).
- The US: the utility's residential tariffs from OpenEI's Utility Rate Database (us_rates.py).
Everywhere else: the house's own hourly price against a fixed price at the same average - does an hourly price
(with Energy Pilot) pay here? Nothing to set; the user may pick their own deal (Denmark, UK) to see what they'd save.
Fetched once a week (deals) and once a day (prices); a source that changes or fails just shows nothing."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import logging
import math
import re
from pathlib import Path
from statistics import median
import time
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

_LOGGER = logging.getLogger(__name__)
ELPRIS = "https://elpris.dk/data/products_{area}.json"
DK_AREA = {"DK1": "131", "DK2": "791"}  # N1 (west) and Radius (east): deals there stand for the whole price area
EDS = "https://api.energidataservice.dk/dataset/DayAheadPrices"
OCTOPUS = "https://api.octopus.energy/v1/products/"
UK_WANT = ("AGILE", "GO-VAR", "COSY", "VAR-", "SNUG", "FLUX-IMPORT")  # import deals any house can take
WEEK, DAY = 7 * 86400, 86400
MIN_DAYS = 7
HEADERS = {"User-Agent": "EnergyPilot (Home Assistant add-on)"}


def _f(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------- Denmark ----------

def dk_offers(data: dict[str, Any], today: str) -> list[dict[str, Any]]:
    """elpris.dk's private deals as {id, name, supplier, url, kind, spot, parts [(from h, to h, kr/kWh)], monthly}, incl. VAT."""
    out = []
    for p in data.get("products") or []:
        if not p.get("private1"):
            continue
        prices = p.get("productPrices") or []
        cur = next((x for x in prices if str(x.get("validFrom") or "") <= today <= str(x.get("validTo") or "9999")), prices[0] if prices else None)
        if not cur or not cur.get("matrix"):
            continue
        parts = []
        for m in cur["matrix"]:
            if (m.get("volumeFrom") or 0) > 0:
                continue  # volume steps: the first one (a house's use) only
            a = _f(m.get("amount"))
            if a is not None:
                parts.append((int(m.get("hoursFrom") or 0), int(m.get("hoursTo") or 24), round(a / 100 * 1.25, 4)))
        if not parts:
            continue
        sup = p.get("supplier") or {}
        out.append({"id": f"dk:{p.get('productId')}-{p.get('productVariantId') or 0}", "name": str(p.get("name") or ""),
                    "supplier": _name(str(sup.get("name") or "")), "url": p.get("orderUrl") or sup.get("homepageUrl") or "",
                    "kind": "spot" if cur.get("additionalNordPoolSpot") else "fixed", "spot": bool(cur.get("additionalNordPoolSpot")),
                    "parts": parts, "monthly": round((_f(cur.get("subscription")) or 0.0) * 1.25, 2)})
    return out


def _name(text: str) -> str:
    """elpris.dk writes "EbbefosEnergihandelA/S": a space before each new word."""
    return re.sub(r"(?<=[a-zæøå])(?=[A-ZÆØÅ])", " ", text).strip()


def dk_part(offer: dict[str, Any], hour: int) -> float:
    """The supplier's own part in an hour (kr/kWh incl. VAT), the spot price not included."""
    return next((a for f, t, a in offer["parts"] if f <= hour < t), offer["parts"][0][2])


# ---------- the comparison ----------

# ---------- deals with time-of-use rules (Australia, Italy, the US) ----------
#
# A deal: {id, name, supplier, url, monthly (money a month), fit (feed-in per kWh, or None = the user's own),
#          partial (True: only the supplier's part - grid charges and taxes come on top, as in Italy),
#          periods: [{"from": "MM-DD", "to": "MM-DD", "rules": [{"days": [0-6] or None, "from": min, "to": min, "rate": x}]}]}
# Rates are per kWh incl. VAT/GST. The first rule that matches wins; a period without one uses its first rate.

def _in_period(md: str, a: str, b: str) -> bool:
    return a <= md <= b if a <= b else (md >= a or md <= b)  # a period over new year (12-01 to 02-28)


def sched_price(deal: dict[str, Any], t: datetime) -> float:
    md, wd, mins = t.strftime("%m-%d"), t.weekday(), t.hour * 60 + t.minute
    periods = deal.get("periods") or []
    per = next((p for p in periods if _in_period(md, p["from"], p["to"])), periods[0] if periods else None)
    if not per or not per.get("rules"):
        return 0.0
    for r in per["rules"]:
        if r.get("days") is not None and wd not in r["days"]:
            continue
        f, e = r.get("from", 0), r.get("to", 1440)
        if (f <= mins < e) if f < e else (mins >= f or mins < e):
            return r["rate"]
    return per["rules"][0]["rate"]


def _sched_deals(rows: list, sched: list[dict[str, Any]], current: str | None, plain: Any, n_days: int) -> list[dict[str, Any]]:
    """Each deal's cost a month: all of them without a battery first, then the 8 cheapest (and the user's own) with
    their own battery plan - the battery would run differently on each."""
    from .engine import Hour, plan_battery

    total = [r["price"] for _, r in rows]
    cur = next((d for d in sched if d["id"] == current), None)
    # What every deal shares (Italy: the grid charges and taxes): the price paid less the deal's own part.
    if any(d.get("partial") for d in sched):
        own = [sched_price(cur, t) if cur else median(sched_price(d, t) for d in sched[:50]) for t, _ in rows]
        common = [tp - o for tp, o in zip(total, own)]
    else:
        common = [0.0] * len(rows)
    per_month = 30 / n_days

    def prices(d: dict[str, Any]) -> tuple[list[float], list[float]]:
        p = [(c if d.get("partial") else 0.0) + sched_price(d, t) for c, (t, _) in zip(common, rows)]
        sell = [d["fit"] if d.get("fit") is not None else r["sell"] for _, r in rows]
        return p, sell

    def quick(d: dict[str, Any]) -> float:
        p, sell = prices(d)
        net = [r["house"] - r["sun"] for _, r in rows]
        return sum(n * (pp if n > 0 else ss) for n, pp, ss in zip(net, p, sell)) + d.get("monthly", 0.0) * n_days / 30

    ranked = sorted(sched, key=quick)
    pick = ranked[:8] + ([cur] if cur and cur not in ranked[:8] else [])
    out = []
    for d in pick:
        p, sell = prices(d)
        if plain:
            hours = [Hour(t, pp, ss, r["house"], r["sun"]) for (t, r), pp, ss in zip(rows, p, sell)]
            end = median(p) * math.sqrt(plain.efficiency)
            pl = plan_battery(hours, plain.min_soc, plain, end_value=end, step_pct=2.0)
            left = ((pl.steps[-1].soc_end if pl.steps else plain.min_soc) - plain.min_soc) / 100 * plain.capacity_kwh
            cost = pl.cost - left * end + d.get("monthly", 0.0) * n_days / 30
        else:
            cost = quick(d)
        out.append({"id": d["id"], "name": d["name"], "supplier": d["supplier"], "url": d.get("url", ""), "kind": "sched",
                    "cost": round(cost * per_month)})
    return out


def _plan_cost(hours: list[Any], b: Any, end: float) -> tuple[list[float], float]:
    """Bought kWh per hour with the battery planned for these prices, and the cost of what is left at the end."""
    from .engine import plan_battery

    p = plan_battery(hours, b.min_soc, b, end_value=end, step_pct=2.0)
    left = ((p.steps[-1].soc_end if p.steps else b.min_soc) - b.min_soc) / 100 * b.capacity_kwh
    return [max(0.0, s.grid_kwh) for s in p.steps], -left * end


def compare(days: list, b: Any | None, tz: Any, offers: list[dict[str, Any]], spot: dict[str, float],
            current: str | None, uk_rates: dict[str, dict[str, float]] | None = None,
            sched: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """Cost a month for each deal (and the user's own) on the last days, cheapest first."""
    from .engine import Hour

    if len(days) < MIN_DAYS:
        return None
    rows = [(datetime.fromisoformat(k + ":00").replace(tzinfo=tz), r) for day in days for k, r in day]
    n_days = len(days)
    plain = replace(b, force={}, targets=(), at=()) if b else None

    def run(prices: list[float]) -> list[float]:
        hours = [Hour(t, p, r["sell"], r["house"], r["sun"]) for (t, r), p in zip(rows, prices)]
        if not plain:  # no battery: what the house buys is what it uses less the sun
            return [max(0.0, r["house"] - r["sun"]) for _, r in rows]
        end = median(prices) * math.sqrt(plain.efficiency)
        bought, _ = _plan_cost(hours, plain, end)
        return bought

    total = [r["price"] for _, r in rows]
    result: dict[str, Any] = {"days": n_days, "deals": []}
    per_month = 30 / n_days
    if offers and spot:  # Denmark
        by = {o["id"]: o for o in offers}
        sp = [spot.get(t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H"), None) for t, _ in rows]
        if sum(1 for x in sp if x is None) > len(sp) * 0.1:
            return None
        sp = [x if x is not None else median([y for y in sp if y is not None]) for x in sp]
        cur = by.get(current or "")
        # The grid charges and taxes: the price paid less the supplier's part (the deal chosen, else the bare spot price).
        own = [((s * 1.25) if (not cur or cur["spot"]) else 0.0) + (dk_part(cur, t.hour) if cur else 0.0) for (t, _), s in zip(rows, sp)]
        common = [tp - o for tp, o in zip(total, own)]
        shapes: dict[str, list[float]] = {}
        spot_shape = [c + s * 1.25 for c, s in zip(common, sp)]
        fixed_shape = [c + 1.0 for c in common]
        shapes["spot"], shapes["fixed"] = run(spot_shape), run(fixed_shape)
        for o in offers:
            bought = shapes["spot" if o["spot"] else "fixed"]
            cost = sum(kwh * (c + (s * 1.25 if o["spot"] else 0.0) + dk_part(o, t.hour))
                       for kwh, c, s, (t, _) in zip(bought, common, sp, rows))
            result["deals"].append({"id": o["id"], "name": o["name"], "supplier": o["supplier"], "url": o["url"],
                                    "kind": o["kind"], "cost": round((cost + o["monthly"] * n_days / 30) * per_month)})
    elif uk_rates:  # UK: each Octopus deal its own plan (a handful)
        for code, info in uk_rates.items():
            rates = info["rates"]
            pr = [rates.get(t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M")) or rates.get(
                t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:00")) for t, _ in rows]
            if sum(1 for x in pr if x is None) > len(pr) * 0.1:
                continue
            fill = median([x for x in pr if x is not None])
            pr = [x if x is not None else fill for x in pr]
            bought = run(pr)
            cost = sum(k * p for k, p in zip(bought, pr)) + info.get("standing", 0.0) * n_days
            result["deals"].append({"id": code, "name": info["name"], "supplier": "Octopus Energy", "url": info.get("url", ""),
                                    "kind": "uk", "cost": round(cost * per_month)})
    elif sched and (sched := [d for d in sched if not d.get("index")]):  # Australia, Italy, the US (sched_price)
        # (an index-linked deal whose index wasn't found is left out: priced on its markup only it would look cheap)
        result["deals"] = _sched_deals(rows, sched, current, plain, n_days)
    else:  # everywhere else: an hourly price against a fixed one at the same average
        flat = sum(total) / len(total)
        hourly = sum(k * p for k, p in zip(run(total), total))
        fixed = sum(k * flat for k in run([flat] * len(total)))
        return {"days": n_days, "mode": "flat", "hourly": round(hourly * per_month), "fixed": round(fixed * per_month),
                "flat_price": round(flat, 3)}
    if not result["deals"]:
        return None
    result["deals"].sort(key=lambda d: d["cost"])
    result["mode"] = "deals"
    result["current"] = next((d for d in result["deals"] if d["id"] == current), None)
    result["best"] = result["deals"][:3]
    result["count"] = len(sched) if sched and not offers and not uk_rates else len(result["deals"])
    del result["deals"]
    return result


# ---------- fetching ----------

class Tariffs:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "energy_pilot_tariffs.json"
        try:
            self.c: dict[str, Any] = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.c = {}
        self.result: dict[str, Any] | None = None
        self._day = None

    def _save(self) -> None:
        try:
            self.path.write_text(json.dumps(self.c, separators=(",", ":")))
        except OSError:
            pass

    def offers(self) -> list[dict[str, Any]]:
        return self.c.get("offers") or []

    def choices(self) -> list[dict[str, str]]:
        """What the user may pick as their own deal."""
        if self.c.get("sched"):
            return sorted(({"id": d["id"], "name": d["name"], "supplier": d["supplier"]} for d in self.c["sched"]),
                          key=lambda o: (o["supplier"].lower(), o["name"].lower()))
        if self.c.get("uk"):
            return [{"id": k, "name": v["name"], "supplier": "Octopus Energy"} for k, v in self.c["uk"].items()]
        return sorted(({"id": o["id"], "name": o["name"], "supplier": o["supplier"]} for o in self.offers()),
                      key=lambda o: (o["supplier"].lower(), o["name"].lower()))

    async def refresh(self, country: str | None, area: str | None, region: str | None,
                      lat: float | None = None, lon: float | None = None) -> None:
        now = time.time()
        try:
            async with aiohttp.ClientSession(headers=HEADERS) as s:
                if country in ("AU", "IT", "US") and lat is not None and lon is not None:
                    if now - self.c.get("sched_at", 0) > WEEK or self.c.get("sched_country") != country:
                        deals = await self._sched(s, country, lat, lon)
                        if deals or self.c.get("sched_country") != country:  # a failed fetch keeps last week's
                            self.c.update(sched=deals, sched_country=country)
                        if not deals:
                            _gone(f"{country} deals")
                        self.c["sched_at"] = now
                if country == "DK" and area in DK_AREA:
                    if now - self.c.get("offers_at", 0) > WEEK or self.c.get("area") != area:
                        async with s.get(ELPRIS.format(area=DK_AREA[area]), timeout=aiohttp.ClientTimeout(total=60)) as r:
                            r.raise_for_status()
                            data = await r.json(content_type=None)
                        offers = dk_offers(data, datetime.now().date().isoformat())
                        if offers or not self.c.get("offers"):  # a changed file keeps last week's deals
                            self.c.update(offers=offers, area=area)
                        if not offers:
                            _gone("elpris.dk deals")
                        self.c["offers_at"] = now
                    if now - self.c.get("spot_at", 0) > DAY or self.c.get("spot_area") != area:
                        spot = await self._dk_spot(s, area)
                        if spot:
                            self.c.update(spot=spot, spot_area=area)
                        else:
                            _gone("Energi Data Service spot prices")
                        self.c["spot_at"] = now
                elif country == "GB" and region:
                    if now - self.c.get("uk_at", 0) > DAY or self.c.get("uk_region") != region:
                        uk = await self._uk(s, region)
                        if uk or self.c.get("uk_region") != region:
                            self.c.update(uk=uk, uk_region=region)
                        if not uk:
                            _gone("Octopus deals")
                        self.c["uk_at"] = now
        except Exception:  # noqa: BLE001 - a comparison never stops anything
            _LOGGER.info("Could not fetch electricity deals", exc_info=True)
        self._save()

    async def _sched(self, s: aiohttp.ClientSession, country: str, lat: float, lon: float) -> list[dict[str, Any]]:
        """Australia, Italy, the US: their own modules; each returns [] when its source fails."""
        if country == "AU":
            from . import au_plans

            if not self.c.get("au_postcode"):
                self.c["au_postcode"] = await au_plans.postcode(s, lat, lon)
            if not self.c["au_postcode"]:
                return []
            return await au_plans.fetch(s, self.c["au_postcode"], self.c.setdefault("au_cache", {}))
        if country == "IT":
            from . import it_offers

            return await it_offers.fetch(s)
        from . import us_rates

        return await us_rates.fetch(s, lat, lon)

    async def _dk_spot(self, s: aiohttp.ClientSession, area: str) -> dict[str, float]:
        """The last 31 days of spot prices (DKK/kWh, excl. VAT), hourly averages, UTC hour keys."""
        end = datetime.now(ZoneInfo("Europe/Copenhagen")).replace(minute=0, second=0, microsecond=0)
        params = {"start": (end - timedelta(days=31)).strftime("%Y-%m-%dT%H:%M"), "end": end.strftime("%Y-%m-%dT%H:%M"),
                  "filter": f'{{"PriceArea":["{area}"]}}', "limit": "4000"}
        async with s.get(EDS, params=params, timeout=aiohttp.ClientTimeout(total=60)) as r:
            r.raise_for_status()
            data = await r.json()
        acc: dict[str, list[float]] = {}
        for rec in data.get("records") or []:
            v = _f(rec.get("DayAheadPriceDKK"))
            if v is None:
                continue
            t = datetime.fromisoformat(rec["TimeUTC"]).strftime("%Y-%m-%dT%H")
            acc.setdefault(t, []).append(v / 1000)
        return {k: round(sum(v) / len(v), 5) for k, v in acc.items()}

    async def _uk(self, s: aiohttp.ClientSession, region: str) -> dict[str, Any]:
        """Octopus' import deals for the region: half-hour rates of the last 31 days (£/kWh incl. VAT) and the
        standing charge (£/day)."""
        async with s.get(OCTOPUS, params={"is_variable": "true", "brand": "OCTOPUS_ENERGY", "is_business": "false"},
                         timeout=aiohttp.ClientTimeout(total=30)) as r:
            r.raise_for_status()
            products = (await r.json()).get("results") or []
        start = (datetime.now(timezone.utc) - timedelta(days=31)).strftime("%Y-%m-%dT%H:%MZ")
        out: dict[str, Any] = {}
        for p in products:
            code = p.get("code") or ""
            if p.get("direction") != "IMPORT" or not code.startswith(UK_WANT) or "PREPAY" in code or "OUTGOING" in code:
                continue
            tariff = f"E-1R-{code}-{region}"
            base = f"{OCTOPUS}{code}/electricity-tariffs/{tariff}/"
            try:
                async with s.get(base + "standard-unit-rates/", params={"period_from": start, "page_size": "1500"},
                                 timeout=aiohttp.ClientTimeout(total=30)) as r:
                    r.raise_for_status()
                    rates_raw = (await r.json()).get("results") or []
                async with s.get(base + "standing-charges/", params={"page_size": "5"}, timeout=aiohttp.ClientTimeout(total=30)) as r:
                    sc = ((await r.json()).get("results") or [{}])[0] if r.status == 200 else {}
            except Exception:  # noqa: BLE001 - one deal missing is fine
                continue
            rates: dict[str, float] = {}
            first = datetime.now(timezone.utc) - timedelta(days=31)
            for x in rates_raw:
                v = _f(x.get("value_inc_vat"))
                a = datetime.fromisoformat(str(x.get("valid_from")).replace("Z", "+00:00"))
                b = datetime.fromisoformat(str(x.get("valid_to")).replace("Z", "+00:00")) if x.get("valid_to") else datetime.now(timezone.utc)
                if v is None:
                    continue
                t = max(a, first).replace(minute=0 if max(a, first).minute < 30 else 30, second=0, microsecond=0)
                while t < b and t < datetime.now(timezone.utc):
                    rates[t.strftime("%Y-%m-%dT%H:%M")] = round(v / 100, 4)
                    t += timedelta(minutes=30)
            if rates:
                out[code] = {"name": p.get("display_name") or code, "rates": rates,
                             "standing": round((_f(sc.get("value_inc_vat")) or 0.0) / 100, 4),
                             "url": "https://octopus.energy/smart/" if code.startswith(("AGILE", "GO", "COSY", "SNUG", "FLUX")) else "https://octopus.energy/"}
        return out

    def compute(self, days: list, b: Any | None, tz: Any, current: str | None) -> dict[str, Any] | None:
        uk = self.c.get("uk") or None
        if uk:
            # the house's hours are whole hours: the half-hours averaged
            uk = {k: {**v, "rates": _hourly(v["rates"])} for k, v in uk.items()}
        return compare(days, b, tz, self.offers() if self.c.get("spot") else [], self.c.get("spot") or {}, current, uk,
                       self.c.get("sched") or None)


def _gone(source: str) -> None:
    """A source that came back empty: most likely its format changed. Said once a week (the next fetch), as a warning -
    those reach the developer by themselves - while the card keeps the last good deals or compares hourly with fixed."""
    # The report names only the error's type and place: the source's name goes into the type, so it shows which.
    kind = type("DealsGone_" + re.sub(r"[^A-Za-z0-9]+", "_", source).strip("_"), (Exception,), {})
    try:
        raise kind(source)
    except Exception:  # noqa: BLE001
        _LOGGER.warning("Electricity deals: %s came back empty - the source may have changed its format", source, exc_info=True)


def _hourly(rates: dict[str, float]) -> dict[str, float]:
    acc: dict[str, list[float]] = {}
    for k, v in rates.items():
        acc.setdefault(k[:13] + ":00", []).append(v)
    return {k: sum(v) / len(v) for k, v in acc.items()}

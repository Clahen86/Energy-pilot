"""Reading coming prices from any price integration, today and tomorrow - and filling what's missing.

Price integrations keep the coming prices in different places and shapes:
- Strømligning: "prices" [{start, end, price}] on the current-price sensor, tomorrow on a separate "…tomorrow…" entity
- Nord Pool: "raw_today" / "raw_tomorrow" [{start, end, value}]
- Energi Data Service: "raw_today" / "raw_tomorrow" / "forecast" [{hour, price}]
- Tibber / Octopus and others: "today" / "tomorrow", lists of numbers or of {startsAt, total}
All of it is read, from the price sensor and from its "tomorrow" companions of the same integration. Hours still
missing (tomorrow's prices not in the integration) are filled from Energy Pilot's own spot prices, moved to the level of
the user's own prices, so the plan always reaches as far as anything is known.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

LIST_KEYS = ("prices", "raw_today", "raw_tomorrow", "today", "tomorrow", "forecast", "forecasts", "rates", "data", "prices_today",
             "prices_tomorrow")  # "forecasts": Amber, "rates": Octopus Energy
TIME_KEYS = ("start", "startsAt", "starts_at", "hour", "time", "from", "start_time", "valid_from", "datetime", "timestamp")
VALUE_KEYS = ("price", "value", "total", "price_inc_vat", "value_inc_vat", "price_ct_per_kwh", "per_kwh", "electricity_price")


def _when(value: Any, tz: ZoneInfo) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=tz)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=tz)
    return None


def _key(dt: datetime, tz: ZoneInfo) -> datetime:
    """A price's start as the local time with its own fixed offset: the two 02:00 of the night the clocks go back are
    two keys (with the zone itself they count as equal - one of the two prices was lost)."""
    loc = dt.astimezone(tz)
    return loc.replace(tzinfo=timezone(loc.utcoffset() or timedelta(0)))


def parse(attrs: dict[str, Any], tz: ZoneInfo, day0: datetime) -> dict[datetime, float]:
    """{start: price per kWh} from one entity's attributes, whatever the shape."""
    per_mwh = str(attrs.get("unit_of_measurement") or "").lower().endswith("/mwh")
    out: dict[datetime, float] = {}
    for key in LIST_KEYS:
        items = attrs.get(key)
        if not isinstance(items, list) or not items:
            continue
        # A bare list of numbers (Nord Pool "today"/"tomorrow", one per hour or quarter).
        if all(isinstance(x, (int, float)) for x in items):
            base = day0 + timedelta(days=1 if "tomorrow" in key else 0)
            # Counted in real time from the local midnight: the day the clocks go back has 25 hours (100 quarters) and
            # the day they go forward 23 (92) - spread over 24 wall-clock hours every price that day was off.
            step = timedelta(minutes=15) if len(items) in (92, 96, 100) else timedelta(hours=1)
            base_utc = base.replace(tzinfo=tz).astimezone(timezone.utc) if base.tzinfo is None else base.astimezone(timezone.utc)
            for i, v in enumerate(items):
                if math.isfinite(float(v)):  # a "nan"/"inf" in the list isn't a price
                    out[_key(base_utc + i * step, tz)] = float(v) / (1000 if per_mwh else 1)
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            start = _when(next((item[k] for k in TIME_KEYS if k in item), None), tz)
            value = next((item[k] for k in VALUE_KEYS if isinstance(item.get(k), (int, float))), None)
            if start is None or value is None or not math.isfinite(float(value)):
                continue
            used = next((k for k in VALUE_KEYS if k in item), "")
            if used.endswith("ct_per_kwh"):  # cents (not "ct" inside "electricity")
                value = value / 100
            elif used == "electricity_price" and abs(value) > 100:
                value = value / 10_000_000  # Zonneplan gives tenths of a micro-euro
            out[_key(start, tz)] = float(value) / (1000 if per_mwh else 1)
    return out


def companions(states: dict[str, dict], entity_id: str) -> list[str]:
    """The price entity and its "tomorrow" companion from the same integration - only one, of the same kind.

    An integration can have several entities for tomorrow: Strømligning has the full price (…_tomorrow_available_vat)
    and the spot price alone (…_tomorrow_spotprice_vat), with and without VAT. Only the one that matches today's
    entity is used (same markers: vat, spot, export, feed-in …), the most alike by name - never a mix.
    Octopus Energy keeps the rates on event entities (…_current_day_rates, …_next_day_rates) beside the
    …_current_rate sensor; Amber keeps the coming prices on a …_forecast sensor beside the …_price one."""
    obj = entity_id.split(".", 1)[1]
    prefix = obj.split("_")[0]
    base = re.sub(r"_(?:current_rate|current_day_rates|next_day_rates|previous_day_rates)$", "", obj)

    def marks(o: str) -> frozenset:
        return frozenset(m for m in ("vat", "spot", "export", "feed", "ex_vat", "excl", "incl", "raw") if m in o)

    def has_list(s: dict) -> bool:
        return any(isinstance((s.get("attributes") or {}).get(k), list) for k in LIST_KEYS)

    out = [entity_id]
    exact = {f"{base}_current_day_rates", f"{base}_next_day_rates", obj.replace("_price", "_forecast")} - {obj}
    for e, s in states.items():
        if e != entity_id and e.split(".", 1)[1] in exact and has_list(s):
            out.append(e)  # Octopus / Amber: the known pair
    if len(out) == 1:
        tomorrow = [e for e, s in states.items() if e != entity_id and has_list(s)
                    and (o := e.split(".", 1)[1]).startswith(prefix + "_")
                    and any(w in o for w in ("tomorrow", "i_morgen", "imorgen", "morgen")) and marks(o) == marks(obj)]
        if tomorrow:
            from difflib import SequenceMatcher

            out.append(max(tomorrow, key=lambda e: SequenceMatcher(None, e.split(".", 1)[1], obj).ratio()))
    return out


def now_price(states: dict[str, dict], entity_id: str | None, tz: ZoneInfo, scale: float = 1.0,
              add: float = 0.0, vat: float = 0.0) -> float | None:
    """The price now: the entity's state, or (an event entity like Octopus') the slot now from its rates. scale: a
    price given in øre/cents is turned into kroner/euros (found by autofix.py). add/vat: a bare spot price (Nord Pool
    in Home Assistant) gets the user's taxes and surcharge, then VAT."""
    if not entity_id or not (s := states.get(entity_id)):
        return None
    try:
        return round((float(s.get("state")) * scale + add) * (1 + vat), 5)
    except (TypeError, ValueError):
        pass
    now = datetime.now(tz)
    prices: dict[datetime, float] = {}
    for e in companions(states, entity_id):
        prices.update(parse((states.get(e) or {}).get("attributes") or {}, tz, now.replace(hour=0, minute=0, second=0, microsecond=0)))
    past = [k for k in prices if k <= now]
    return round((prices[max(past)] * scale + add) * (1 + vat), 5) if past else None


def collect(states: dict[str, dict], entity_id: str | None, own: list[dict[str, Any]], tz: ZoneInfo,
            service: list[dict[str, Any]] | None = None, scale: float = 1.0, add: float = 0.0,
            vat: float = 0.0) -> tuple[dict[datetime, float], dict[str, Any]]:
    """All known prices from the integration, with the missing hours filled from Energy Pilot's own prices.
    Returns (prices, info) - info says what was filled and if tomorrow is still missing."""
    now = datetime.now(tz)
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    prices: dict[datetime, float] = {}
    if entity_id:
        for e in companions(states, entity_id):
            prices.update(parse((states.get(e) or {}).get("attributes") or {}, tz, day0))
        if not prices and not service and not own and "tempo" not in entity_id:
            # A fixed price (an input_number, a template with one figure), nothing coming and no spot prices of its own
            # to fill with (outside the markets Energy Pilot knows): the same price every hour
            # of today and tomorrow - else there were no prices at all, and so no plan.
            try:
                flat = float((states.get(entity_id) or {}).get("state"))
            except (TypeError, ValueError):
                flat = None
            if flat is not None and math.isfinite(flat):
                base = day0.astimezone(timezone.utc)
                prices = {_key(base + timedelta(hours=i), tz): flat for i in range(48)}
        for p in service or []:  # prices an integration gives through its action
            when = _when(p.get("start"), tz)
            if when is not None and isinstance(p.get("price"), (int, float)) and math.isfinite(float(p["price"])):
                prices[_key(when, tz)] = float(p["price"])
        if "tempo" in entity_id:
            from . import tempo  # EDF Tempo: the prices come from the day colours

            if tempo.found(states):
                prices.update(tempo.prices(states, tz, now))
                own = []  # spot prices say nothing about tomorrow's colour - don't fill with them
        if scale != 1.0 or add or vat:
            prices = {k: round((v * scale + add) * (1 + vat), 5) for k, v in prices.items()}
    mine = {}
    for p in own or []:
        when = _when(p.get("start"), tz)
        if when is not None and isinstance(p.get("price"), (int, float)) and math.isfinite(float(p["price"])):
            mine[_key(when, tz)] = float(p["price"])
    filled = 0
    shown_until = day0 + timedelta(days=2)  # the plan shows today and tomorrow
    if prices and mine:
        # Same level as the user's own prices: the mean difference where both are known.
        both = [k for k in mine if k in prices]
        offset = sum(prices[k] - mine[k] for k in both) / len(both) if both else 0.0
        last = max(prices)
        # The last known price holds for its whole slot: an hourly price at 23:00 covers up to midnight. Own prices in
        # quarters (23:15, 23:30, 23:45) were taken for missing hours - and the plan said tomorrow was estimated.
        keys = sorted(prices)
        step = min((b - a for a, b in zip(keys, keys[1:]) if b > a), default=timedelta(hours=1))
        covered = last + min(step, timedelta(hours=1))
        for k, v in mine.items():
            if k >= covered:
                prices[k] = round(v + offset, 4)
                # Counted only where the plan shows it: with all of tomorrow known, the spot prices reaching into the
                # day after are no "tomorrow estimated" (the note said so while every hour of tomorrow was known).
                if k < shown_until:
                    filled += 1
    elif not prices:
        prices = dict(mine)
    tomorrow = day0 + timedelta(days=1)
    has_tomorrow = any(tomorrow <= k < tomorrow + timedelta(days=1) for k in prices)
    return prices, {"filled": filled, "tomorrow_missing": now.hour >= 14 and not has_tomorrow}

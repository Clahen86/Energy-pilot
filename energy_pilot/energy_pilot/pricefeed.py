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

import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

LIST_KEYS = ("prices", "raw_today", "raw_tomorrow", "today", "tomorrow", "forecast", "forecasts", "rates", "data", "prices_today",
             "prices_tomorrow")  # "forecasts": Amber, "rates": Octopus Energy
TIME_KEYS = ("start", "startsAt", "starts_at", "hour", "time", "from", "start_time", "valid_from")
VALUE_KEYS = ("price", "value", "total", "price_inc_vat", "value_inc_vat", "price_ct_per_kwh", "per_kwh")


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
            step = timedelta(hours=24 / len(items)) if len(items) in (24, 23, 25, 96, 92, 100) else timedelta(hours=1)
            for i, v in enumerate(items):
                out[base + i * step] = float(v) / (1000 if per_mwh else 1)
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            start = _when(next((item[k] for k in TIME_KEYS if k in item), None), tz)
            value = next((item[k] for k in VALUE_KEYS if isinstance(item.get(k), (int, float))), None)
            if start is None or value is None:
                continue
            if "ct" in next((k for k in VALUE_KEYS if k in item), ""):
                value = value / 100
            out[start.astimezone(tz)] = float(value) / (1000 if per_mwh else 1)
    return out


def companions(states: dict[str, dict], entity_id: str) -> list[str]:
    """The price entity and its "tomorrow" companions from the same integration (same name prefix).

    Octopus Energy keeps today's and tomorrow's rates on event entities (…_current_day_rates, …_next_day_rates)
    beside the …_current_rate sensor; import and export are kept apart."""
    obj = entity_id.split(".", 1)[1]
    prefix = obj.split("_")[0]
    export = "export" in obj
    base = re.sub(r"_(?:current_rate|current_day_rates|next_day_rates|previous_day_rates)$", "", obj)
    out = [entity_id]
    for e, s in states.items():
        if e == entity_id:
            continue
        o = e.split(".", 1)[1]
        if ("export" in o) != export or not any(isinstance((s.get("attributes") or {}).get(k), list) for k in LIST_KEYS):
            continue
        tomorrow = o.startswith(prefix + "_") and any(w in o for w in ("tomorrow", "i_morgen", "imorgen", "morgen"))
        octopus = o in (f"{base}_current_day_rates", f"{base}_next_day_rates")
        if tomorrow or octopus:
            out.append(e)
    return out


def now_price(states: dict[str, dict], entity_id: str | None, tz: ZoneInfo) -> float | None:
    """The price now: the entity's state, or (an event entity like Octopus') the slot now from its rates."""
    if not entity_id or not (s := states.get(entity_id)):
        return None
    try:
        return float(s.get("state"))
    except (TypeError, ValueError):
        pass
    now = datetime.now(tz)
    prices: dict[datetime, float] = {}
    for e in companions(states, entity_id):
        prices.update(parse((states.get(e) or {}).get("attributes") or {}, tz, now.replace(hour=0, minute=0, second=0, microsecond=0)))
    past = [k for k in prices if k <= now]
    return prices[max(past)] if past else None


def collect(states: dict[str, dict], entity_id: str | None, own: list[dict[str, Any]], tz: ZoneInfo) -> tuple[dict[datetime, float], dict[str, Any]]:
    """All known prices from the integration, with the missing hours filled from Energy Pilot's own prices.
    Returns (prices, info) - info says what was filled and if tomorrow is still missing."""
    now = datetime.now(tz)
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    prices: dict[datetime, float] = {}
    if entity_id:
        for e in companions(states, entity_id):
            prices.update(parse((states.get(e) or {}).get("attributes") or {}, tz, day0))
    mine = {}
    for p in own or []:
        when = _when(p.get("start"), tz)
        if when is not None and isinstance(p.get("price"), (int, float)):
            mine[when.astimezone(tz)] = float(p["price"])
    filled = 0
    if prices and mine:
        # Same level as the user's own prices: the mean difference where both are known.
        both = [k for k in mine if k in prices]
        offset = sum(prices[k] - mine[k] for k in both) / len(both) if both else 0.0
        last = max(prices)
        for k, v in mine.items():
            if k > last:
                prices[k] = round(v + offset, 4)
                filled += 1
    elif not prices:
        prices = dict(mine)
    tomorrow = day0 + timedelta(days=1)
    has_tomorrow = any(tomorrow <= k < tomorrow + timedelta(days=1) for k in prices)
    return prices, {"filled": filled, "tomorrow_missing": now.hour >= 14 and not has_tomorrow}

"""What kind of battery it is - and so what a kWh through it wears it, how low it may go and how efficient it is.

Found by itself, from what Home Assistant already knows: the inverter's own "battery type" setting (Deye, Growatt,
Victron, Solis …), the battery's model (BYD, Pylontech … are LFP; Powerwall 2 and LG RESU are NMC), a cycle rating the
integration shows, and - last - a learned efficiency under 85 % (lead). Otherwise LFP, the common one.
The user can pick the type, say what the battery cost, or set the wear outright (Advanced).
"""

from __future__ import annotations

import re
from typing import Any

# cycles to end of life, the lowest level it likes, round-trip efficiency, a typical price per kWh (DKK)
TYPES: dict[str, dict[str, float]] = {
    "lfp": {"cycles": 6000, "min_soc": 10, "eff": 0.95, "price_dkk": 1600},
    "nmc": {"cycles": 3500, "min_soc": 10, "eff": 0.93, "price_dkk": 2500},
    "sodium": {"cycles": 4000, "min_soc": 10, "eff": 0.92, "price_dkk": 1200},
    "lead": {"cycles": 1000, "min_soc": 50, "eff": 0.80, "price_dkk": 1000},
}
# DKK per unit of each currency (rounded - only for the typical battery price)
DKK_PER = {"DKK": 1, "EUR": 7.46, "GBP": 8.7, "NOK": 0.65, "SEK": 0.66, "USD": 6.9, "AUD": 4.5, "NZD": 4.1, "CAD": 5.0,
           "PLN": 1.73, "CHF": 7.9, "CZK": 0.3, "HUF": 0.019}

_LEAD = r"lead|agm|gel|flooded|bly|blei|plomb|opzv|opzs|\bpb\b"
_LFP = r"lithium|lifepo|lfp|li-?ion|\bli\b"
MODELS = [  # the battery's or inverter's model name -> type (first match wins)
    (r"powerwall ?3", "lfp"),
    (r"powerwall|resu|lg ?chem|tesla", "nmc"),
    (r"byd|pylontech|growatt ?ark|apx|luna|sigen|alpha ?ess|seplos|jk ?bms|eve|lifepo|dyness|weco|sofar ?amass|"
     r"solax ?triple|huawei|givenergy|fox ?ess|mira|ecoflow|anker|zendure|marstek", "lfp"),
    (r"sodium|natrium|na-?ion", "sodium"),
]


def detect(states: dict[str, Any], model: str | None, soc_entity: str | None, learned_eff: float | None,
           eff_seen: int = 0) -> dict[str, Any]:
    """{"type": "lfp" …, "why": "inverter"/"model"/"efficiency"/"default", "cycles": n or None}."""
    cycles = None
    if soc_entity:
        a = (states.get(soc_entity) or {}).get("attributes") or {}
        for k, v in a.items():
            if "cycle" in str(k).lower() and "rating" in str(k).lower():
                try:
                    cycles = int(float(v))
                except (TypeError, ValueError):
                    pass
    for e, s in states.items():
        if e.split(".")[0] in ("select", "sensor") and re.search(r"battery_?type|batterietyp|type_de_batterie", e):
            st = str((s or {}).get("state") or "").lower()
            if re.search(_LEAD, st):
                return {"type": "lead", "why": "inverter", "cycles": cycles}
            if re.search(_LFP, st):
                return {"type": "lfp", "why": "inverter", "cycles": cycles}
    text = (model or "").lower()
    for pat, t in MODELS:
        if text and re.search(pat, text):
            return {"type": t, "why": "model", "cycles": cycles}
    if learned_eff is not None and eff_seen >= 3 and learned_eff < 0.85:
        return {"type": "lead", "why": "efficiency", "cycles": cycles}
    return {"type": "lfp", "why": "default" if cycles is None else "model", "cycles": cycles}


def wear(kind: str, currency: str, capacity_kwh: float | None = None, price: float | None = None,
         cycles: int | None = None) -> float:
    """Money per kWh into or out of the battery: its price over every kWh it will move in its life (both ways)."""
    t = TYPES.get(kind) or TYPES["lfp"]
    n = cycles or t["cycles"]
    if price and capacity_kwh:
        per_kwh = price / capacity_kwh  # what the user paid
    else:
        per_kwh = t["price_dkk"] / DKK_PER.get(currency.upper(), 7.46)
    return round(per_kwh / (n * 2), 3)

"""The sensor finder: learned from every installation's setup which sensor each integration uses for what.

Two tables, both counted per home (one home is one vote):
- keys:  the integration's own translation key -> the role ("solarman|battery_soc" -> battery_soc). The same in every
         home with that integration - the strongest clue there is.
- names: the entity's name with the device's name taken out ("solarman|sensor|battery" -> battery_soc).
Only what at least two homes agree on (three in four of them) is kept. Energy Pilot uses it where its own rules
found nothing. Prints Markdown for the job summary; writes the model to the given file.

    python training/sensors.py setups.json model.json
"""
from __future__ import annotations

from collections import defaultdict
import json
import sys

ROLES = {"battery_power", "battery_soc", "pv_power", "grid_power", "house_power", "solar_today", "ev_power", "ev_plug",
         "ev_soc", "price", "sell_price"}
MIN_HOMES = 2
AGREE = 0.75


def build(rows: list[dict]) -> dict:
    keys: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    names: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for r in rows:
        for dev in r.get("devices") or []:
            for e in dev.get("entities") or []:
                role, plat, name = e.get("use"), e.get("platform"), str(e.get("name") or "")
                if role not in ROLES or not plat or "." not in name:
                    continue
                if e.get("key"):
                    keys[f"{plat}|{e['key']}"][role].add(r["home"])
                dom, obj = name.split(".", 1)
                if obj.startswith("<device>_") and "<" not in obj[9:]:
                    names[f"{plat}|{dom}|{obj[9:]}"][role].add(r["home"])

    def keep(table: dict) -> dict:
        out = {}
        for k, votes in table.items():
            role, homes = max(votes.items(), key=lambda kv: len(kv[1]))
            total = len(set().union(*votes.values()))
            if len(homes) >= MIN_HOMES and len(homes) >= AGREE * total:
                out[k] = {"role": role, "n": len(homes)}
        return out

    return {"version": 1, "keys": keep(keys), "names": keep(names)}


def safe_change(old: dict | None, new: dict) -> str | None:
    """Why the new model must not go out, or None. A night that loses half the rules (or turns many around) is
    more likely a fault in the training or the data than a real change - it waits for a person to look."""
    if not old:
        return None
    o = {**(old.get("keys") or {}), **(old.get("names") or {})}
    n = {**new["keys"], **new["names"]}
    if len(o) >= 6 and len(n) < len(o) / 2:
        return f"the rules fell from {len(o)} to {len(n)}"
    flipped = [k for k in o if k in n and o[k]["role"] != n[k]["role"]]
    if len(flipped) >= 3 and len(flipped) > len(o) * 0.2:
        return f"{len(flipped)} rules changed role"
    return None


def main() -> None:
    rows = json.load(open(sys.argv[1]))
    model = build(rows)
    old = None
    if len(sys.argv) > 3:
        try:
            old = (json.load(open(sys.argv[3])).get("common") or {}).get("sensors")
        except (OSError, ValueError):
            old = None
    why = safe_change(old, model)
    if why:
        print(f"## Sensorfinder\n\n❌ Ikke sendt ud: {why}. Gårsdagens model bruges stadig - kig på det, før den sendes.")
        sys.exit(1)
    json.dump(model, open(sys.argv[2], "w"))
    plats = sorted({k.split("|")[0] for k in list(model["keys"]) + list(model["names"])})
    print("## Sensorfinder\n")
    print(f"{len(rows)} opsætninger. Lærte {len(model['keys'])} nøgler og {len(model['names'])} navne "
          f"fra {len(plats)} integrationer: {', '.join(plats) or '-'}.")


if __name__ == "__main__":
    main()

"""The main fuse per phase: the house can draw unevenly, under the kW limit as a whole but over the fuse on one phase.

A meter with one current per phase (a SlimmeLezer / DSMR, HomeWizard P1, Tibber Pulse …) is found by itself: three
sensors in amps for L1, L2 and L3 of the same meter. With the fuse set (amps), the battery's grid charge and the car
give way within a minute when the busiest phase comes close - the plan still uses the kW limit.
"""

from __future__ import annotations

from datetime import datetime
import math
import re
import time
from typing import Any

VOLT = 230
MARGIN_A = 1.0  # a little under the fuse, for the next minute
FROZEN_S = 15 * 60  # all three phases unchanged this long: the meter stopped (a P1 dongle gone) - not read

_PHASE = re.compile(r"(?:^|[_.])(?:l|phase_?|fase_?)([123])(?:$|_)", re.I)
_CURRENT = re.compile(r"current|stroom|strom|ampere|courant", re.I)
# not the grid meter: the inverter's own grid port, the PV, the battery, a charger, one circuit
_NOT = re.compile(r"inverter|deye|growatt|solis|sungrow|goodwe|huawei|sofar|solax|foxess|victron|fronius|solaredge|"
                  r"\bpv|_pv|solar|batt|charger|wallbox|keba|easee|zaptec|ev_|_ev\b|car|load|output|backup|eps|"
                  r"heat|pump|plug|socket|shelly_plug", re.I)


def find(states: dict[str, Any]) -> list[str] | None:
    """The grid meter's three phase currents [L1, L2, L3], or None: same name but for the phase number, in amps."""
    groups: dict[str, dict[str, str]] = {}
    for eid, st in states.items():
        if not eid.startswith("sensor.") or _NOT.search(eid):
            continue
        attrs = (st or {}).get("attributes") or {}
        if str(attrs.get("unit_of_measurement") or "") != "A" and attrs.get("device_class") != "current":
            continue
        if not _CURRENT.search(eid) or not (m := _PHASE.search(eid)):
            continue
        key = eid[:m.start()] + "#" + eid[m.end():]
        groups.setdefault(key, {})[m.group(1)] = eid
    full = [g for g in groups.values() if len(g) == 3]
    if len(full) != 1:
        return None  # none, or more meters than one: not guessed
    g = full[0]
    return [g["1"], g["2"], g["3"]]


def _age(st: dict[str, Any], now: float) -> float | None:
    try:
        return now - datetime.fromisoformat(str(st.get("last_updated") or st.get("last_changed"))).timestamp()
    except (TypeError, ValueError):
        return None


def worst(states: dict[str, Any], ents: list[str] | None, now: float | None = None) -> float | None:
    """The busiest phase now (A), or None when a phase isn't read - or the meter froze: all three phases unchanged
    for a quarter of an hour (Home Assistant keeps the last value when a dongle stops; the guard would go on trusting
    an old number). One phase steady (nothing on it) is normal: only all three at once count."""
    if not ents:
        return None
    now = time.time() if now is None else now
    ages = [_age(states.get(e) or {}, now) for e in ents]
    if all(a is not None and a > FROZEN_S for a in ages):
        return None
    vals = []
    for e in ents:
        try:
            v = abs(float((states.get(e) or {}).get("state")))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(v):
            return None  # "nan"/"inf" from a template or MQTT sensor: not read (a NaN slipped past the fuse guard)
        vals.append(v)
    return max(vals)


def room_a(states: dict[str, Any], ents: list[str] | None, fuse_a: float | None) -> float | None:
    """Amps left on the busiest phase before the fuse (with a margin) - None without a fuse or a meter."""
    if not fuse_a:
        return None
    w = worst(states, ents)
    return None if w is None else float(fuse_a) - MARGIN_A - w


L2 = re.compile(r"(?i)(?:^|[._])(?:l2|phase_?[2b]|s_phase)(?:[._]|$)")
L3 = re.compile(r"(?i)(?:^|[._])(?:l3|phase_?[3c]|t_phase)(?:[._]|$)")


def battery_phases(max_charge_kw: float, ents: list[str] | None = None) -> int:
    """How many phases the battery's charging is spread on: three only when the inverter shows its own second and
    third phase (both an L2 and an L3 entity - one alone proves nothing) - a big battery alone says nothing either
    (single-phase hybrids go to 6-8 kW). When in doubt one: the guard is then too careful at worst, never too bold."""
    ents = ents or []
    return 3 if max_charge_kw > 3.7 and any(L2.search(e) for e in ents) and any(L3.search(e) for e in ents) else 1

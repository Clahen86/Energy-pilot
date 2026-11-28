"""Controls written straight to the inverter's registers, when its integration has no entity for them.

davidrapan/ha-solarman can write any register itself (solarman.write_multiple_registers - what owners already do by
hand in automations). A home with an older or personalized definition file (a ZCS 3000SP from a hand-made YAML, a Deye
on an old one) has the inverter but not the profile's selects and numbers. Then the profile's control is written to its
register instead - the same value the entity would have written, from davidrapan's own definitions.

Never blind: the registers are read first, and only used when every one of them holds a value that fits (a Work Mode
of 0-4, times that are times, powers in range) - and, where the definitions say how, when the inverter's own type
register says it is that model. Anything else: not used, and the app says which controls are missing and what to do.
"""

from __future__ import annotations

import re
from typing import Any

SOLARMAN_WRITE = "solarman.write_multiple_registers"
SOLARMAN_READ = "solarman.read_holding_registers"

# ---------- Sofar HYD-ES / ME 3000-SP / ZCS Azzurro 3000SP: sofar_hybrid.yaml ----------
_SOFAR_ME = {
    "definition": "Sofar HYD 3000~6000-ES | ME 3000-SP",
    "identify": None,  # its definition has no model register: the serial number below, and the seven values, must fit
    "serial": (0x2001, 7),  # ASCII, two characters a register
    "controls": {
        r"select\..*(?<!energy_pattern_)work_mode$": {"addr": 0x1200, "lookup": {"Auto": 0, "Time of Use": 1, "Timed": 2, "Passive": 3, "Peak Shaving": 4}},
        r"time\..*timed_charge_start$": {"addr": 0x1201, "time": 256},
        r"time\..*timed_charge_end$": {"addr": 0x1202, "time": 256},
        r"time\..*timed_discharge_start$": {"addr": 0x1203, "time": 256},
        r"time\..*timed_discharge_end$": {"addr": 0x1204, "time": 256},
        r"number\..*timed_charge_power$": {"addr": 0x1205, "min": 0, "max": 3000},
        r"number\..*timed_discharge_power$": {"addr": 0x1206, "min": 0, "max": 3000},
    },
}

# ---------- Deye hybrid via Solarman: deye_hybrid.yaml (single phase, LP1) and deye_p3.yaml (three phase) ----------
_TOU = {"Disabled": 0x00, "Monday": 0x03, "Tuesday": 0x05, "Wednesday": 0x09, "Thursday": 0x11, "Friday": 0x21,
        "Saturday": 0x41, "Sunday": 0x81, "Weekdays": 0x3F, "Weekend": 0xC1, "Week": 0xFF}
_PROG = {"Disabled": 0, "Grid": 1, "Generator": 2, "Both": 3}


def _deye(name: str, ids: set[int], a: dict[str, int], mask: bool) -> dict:
    # Selling (Work Mode, export power) and the grid charge current are put back afterwards from the entities'
    # states - a register has none to put back, so those are never written by register: no selling that way, and
    # the grid charge runs at the inverter's own current.
    controls: dict[str, dict] = {
        r"select\..*time_of_use$": {"addr": a["tou"], "lookup": _TOU, "max": 0xFF},
        r"switch\..*battery_grid_charging$": {"addr": a["grid"], "switch": True},
    }
    for n in range(1, 7):
        controls[rf"number\..*program_{n}_soc$"] = {"addr": a["soc"] + n - 1, "min": 0, "max": 100}
        # Single phase: the programme's charge source is the word's two lowest bits (the rest is kept as it is)
        controls[rf"select\..*program_{n}_charging$"] = {"addr": a["prog"] + n - 1, "lookup": _PROG, "max": 0xFF,
                                                          **({"mask": 0x3} if mask else {})}
    return {"definition": name, "identify": (0x0000, ids), "controls": controls}


_H = {"tou": 0x00F8, "grid": 0x00E8, "soc": 0x010C, "prog": 0x0112}
_P = {"tou": 0x0092, "grid": 0x0082, "soc": 0x00A6, "prog": 0x00AC}

# profile key -> the register variants it can be (the first whose identity and values fit is used)
MAPS: dict[str, list[dict]] = {
    "sofar_me": [_SOFAR_ME],
    "solarman": [
        # (0x0103/0x0104 are Deye's off-grid and storage-only types: never)
        _deye("Deye Hybrid (single phase)", {0x0003, 0x0300}, _H, mask=True),
        _deye("Deye P3 (three phase)", {0x0005, 0x0500, 0x0006, 0x0007, 0x0600, 0x0008, 0x0601}, _P, mask=False),
    ],
}


def addresses(variant: dict) -> list[int]:
    out = {c["addr"] for c in variant["controls"].values()}
    if variant.get("serial"):
        out |= set(range(variant["serial"][0], variant["serial"][0] + variant["serial"][1]))
    return sorted(out)


def serial(variant: dict, raw: dict[int, int]) -> str | None:
    """The serial number in the inverter's own registers, when it reads like one (letters and digits, at least 6)."""
    start, count = variant["serial"]
    words = [raw.get(a) for a in range(start, start + count)]
    if any(not isinstance(w, int) for w in words):
        return None
    text = b"".join(int(w).to_bytes(2, "big") for w in words).decode("latin-1").strip("\x00 ")
    return text if len(text) >= 6 and text.isascii() and text.isalnum() else None


def blocks(addrs: list[int], gap: int = 16, most: int = 120) -> list[tuple[int, int]]:
    """(start, count) reads covering the addresses - neighbours together, so a profile is one or two reads."""
    out: list[tuple[int, int]] = []
    for a in sorted(set(addrs)):
        if out and a - (out[-1][0] + out[-1][1]) <= gap and a - out[-1][0] < most:
            out[-1] = (out[-1][0], a - out[-1][0] + 1)
        else:
            out.append((a, 1))
    return out


def fits(spec: dict, raw: int) -> bool:
    """A value read from the register that this control could hold."""
    if not isinstance(raw, int) or not 0 <= raw <= 0xFFFF:
        return False
    if "time" in spec:
        h, m = divmod(raw, spec["time"])
        return 0 <= h <= 23 and 0 <= m <= 59
    if spec.get("switch"):
        return raw in (0, 1)
    if "lookup" in spec:
        if "max" in spec:  # a bit field (days, a programme's sources): any word up to its width
            return raw <= spec["max"]
        return raw in set(spec["lookup"].values())
    return spec.get("min", 0) <= raw <= spec.get("max", 0xFFFF)


def identified(variant: dict, raw: dict[int, int], known_serial: str | None = None) -> bool:
    """The inverter says it is this one: its type register - or its serial number (the same as Home Assistant's,
    when Home Assistant knows it)."""
    ident = variant.get("identify")
    if ident:
        return raw.get(ident[0]) in ident[1]
    if variant.get("serial"):
        sn = serial(variant, raw)
        if not sn:
            return False
        return not known_serial or known_serial.strip().upper() in sn.upper() or sn.upper() in known_serial.strip().upper()
    return False


def pick(key: str, raw: dict[int, int], known_serial: str | None = None) -> dict | None:
    """The variant these registers are: it is identified, and every control's value fits."""
    for variant in MAPS.get(key) or []:
        if not identified(variant, raw, known_serial):
            continue
        if all(c["addr"] in raw and fits(c, raw[c["addr"]]) for c in variant["controls"].values()):
            return variant
    return None


def encode(spec: dict, kind: str, value: Any, ctx: dict[str, Any], now: int | None) -> int | None:
    """The word to write for what the profile's step means (None: no value it can write)."""
    try:
        if kind == "time":
            h, m = str(value).split(":")[:2]
            word = int(h) * spec["time"] + int(m)
        elif kind == "grid":
            word = 1 if ctx.get("grid_charge", True) else 0
        elif kind in ("on", "off"):
            word = 1 if kind == "on" else 0
        elif kind == "select":
            code = spec["lookup"].get(str(value))
            if code is None:
                return None
            word = (int(now or 0) & ~spec["mask"]) | code if spec.get("mask") else code
        elif kind == "number":
            word = round(float(value) / spec.get("scale", 1))
            word = max(spec.get("min", 0), min(spec.get("max", 0xFFFF), word))
        else:
            return None
    except (TypeError, ValueError, KeyError):
        return None
    return word if fits(spec, word) else None


def nice(pattern: str) -> str:
    """A control's pattern as a person would say it: r"number\\..*timed_charge_power$" -> "Timed Charge Power"."""
    tail = re.sub(r"\(\?<?[!=][^)]*\)", "", pattern)  # look-arounds
    tail = tail.split(".*")[-1].strip("$^")
    tail = re.sub(r"[\\()?|\[\]+*]", " ", tail).replace("_", " ")
    return " ".join(w.capitalize() for w in tail.split()) or pattern

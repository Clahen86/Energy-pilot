"""The sky network: houses help each other see clouds and grid failures coming.

Every quarter of an hour (when sharing is on) Energy Pilot tells the report worker how its sun compares with its own
forecast right now - a ratio, so the size of the panels doesn't matter - and whether its grid is down, for a cell of
about 10 x 10 km (never the position). It gets back the same for the cells around it.

- Clouds: houses upwind see a cloud (or clear sky) before this one. Where the wind takes their ratio within the next
  three hours, the sun forecast for that hour is pulled towards it - most for the next hour, less further out.
- Grid: when several houses within 30 km lose the grid at the same time, the storm watch (if it's on) keeps the
  battery full for the next hours, in case it reaches this house too.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import math
import time
from typing import Any

CELL_LAT, CELL_LON = 0.1, 0.15  # ~11 x 10 km in Denmark
EVERY_S = 900
UPWIND_DEG = 35  # a cell this far off the wind's line still counts
AHEAD_H = 3.0
OUTAGE_KM = 30.0
OUTAGE_HOLD_H = 3


def cell(lat: float, lon: float) -> str:
    """The cell a position lies in - its south-west corner, rounded so the house can't be found."""
    return f"{math.floor(lat / CELL_LAT) * CELL_LAT:.1f}|{math.floor(lon / CELL_LON) * CELL_LON:.2f}"


def middle(c: str) -> tuple[float, float]:
    a, b = c.split("|")
    return float(a) + CELL_LAT / 2, float(b) + CELL_LON / 2


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> tuple[float, float]:
    """Distance (km) and bearing (degrees, 0 = north) from 1 to 2 - flat earth, fine within 100 km."""
    dy = (lat2 - lat1) * 111.2
    dx = (lon2 - lon1) * 111.2 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy), (math.degrees(math.atan2(dx, dy)) + 360) % 360


def upwind(near: list[dict[str, Any]], home: tuple[float, float], wind_from: float, wind_kmh: float) -> list[tuple[float, float, int]]:
    """(hours until it gets here, ratio, houses) for cells upwind, within AHEAD_H hours."""
    if not wind_kmh or wind_kmh < 5:
        return []  # hardly any wind: the clouds stay where they are
    out = []
    for c in near:
        if c.get("ratio") is None or int(c.get("n") or 0) < 2:
            continue
        dist, bearing = _km(home[0], home[1], float(c["lat"]), float(c["lon"]))
        off = abs((bearing - wind_from + 180) % 360 - 180)
        if dist < 3 or off > UPWIND_DEG:
            continue
        hours = dist * math.cos(math.radians(off)) / wind_kmh
        if hours <= AHEAD_H:
            out.append((hours, float(c["ratio"]), int(c["n"])))
    return out


def adjust(near: list[dict[str, Any]], home: tuple[float, float] | None, times: list[datetime], sun: list[float],
           now: datetime, weather: Any) -> list[float]:
    """The sun forecast, pulled towards what the houses upwind see now, for the hours it will reach this house."""
    if not near or not home or weather is None:
        return sun
    w = weather.at(now) or {}
    if w.get("wind_dir") is None or w.get("wind") is None:
        return sun
    seen = upwind(near, home, float(w["wind_dir"]), float(w["wind"]))
    if not seen:
        return sun
    out = list(sun)
    for i, t in enumerate(times):
        mid = (t + timedelta(minutes=30) - now).total_seconds() / 3600
        if mid < 0 or mid > AHEAD_H:
            continue
        hits = [(r, n) for h, r, n in seen if mid - 0.5 <= h < mid + 0.5]  # it gets here within this hour
        n = sum(n for _, n in hits)
        if n < 2:
            continue
        ratio = max(0.1, min(1.5, sum(r * k for r, k in hits) / n))
        weight = 0.7 if mid <= 1 else 0.5 if mid <= 2 else 0.3
        out[i] = sun[i] * ((1 - weight) + weight * ratio)
    return out


def outage_near(near: list[dict[str, Any]], home: tuple[float, float] | None) -> dict[str, Any] | None:
    """Houses within OUTAGE_KM that lost the grid: {"houses", "km"} or None. Two in a cell, or half of those reporting."""
    if not near or not home:
        return None
    hit, closest = 0, None
    for c in near:
        down, rep = int(c.get("down") or 0), int(c.get("reporting") or 0)
        if down < 2 or down * 2 < rep:
            continue
        dist, _ = _km(home[0], home[1], float(c["lat"]), float(c["lon"]))
        if dist <= OUTAGE_KM:
            hit += down
            closest = dist if closest is None else min(closest, dist)
    return {"houses": hit, "km": round(closest)} if hit else None


def storm(out: dict[str, Any] | None, now: datetime) -> dict[str, Any] | None:
    """A grid failure nearby as a storm window for storm.targets: keep the battery full the next hours."""
    if not out:
        return None
    return {"from": now.isoformat(), "to": (now + timedelta(hours=OUTAGE_HOLD_H)).isoformat(), "gust": None,
            "kind": "outage", "houses": out["houses"], "km": out["km"]}


class Sky:
    """What the houses around have seen lately, and this house's own share - kept by the telemetry round."""

    def __init__(self) -> None:
        self.near: list[dict[str, Any]] = []
        self.t = 0.0
        self.sent = 0.0

    def fresh(self) -> list[dict[str, Any]]:
        return self.near if time.time() - self.t < 1800 else []

    def info(self, home: tuple[float, float] | None) -> dict[str, Any]:
        near = self.fresh()
        houses = sum(int(c.get("n") or 0) for c in near)
        return {"houses": houses, "cells": len(near), "outage": outage_near(near, home)}


GRID_V_KNOWN = ("sensor.growatt_sph_grid_voltage", "sensor.growatt_sph_ac_voltage")
GRID_V_WORDS = ("grid_voltage", "ac_input_voltage", "grid_l1_voltage", "net_spaending", "netspaending")


def grid_voltage_entity(states: dict[str, Any]) -> str | None:
    """A sensor with the grid's voltage (in V), if the inverter has one."""
    for e in GRID_V_KNOWN:
        if e in states:
            return e
    for e, st in states.items():
        if not e.startswith("sensor.") or not any(w in e for w in GRID_V_WORDS):
            continue
        if str((st.get("attributes") or {}).get("unit_of_measurement") or "").upper() == "V":
            return e
    return None


def grid_down(states: dict[str, Any], entity: str | None) -> bool | None:
    """True when the grid's voltage is gone, False when it's there, None when it can't be told."""
    st = states.get(entity or "") or {}
    try:
        return float(st.get("state")) < 100
    except (TypeError, ValueError):
        return None

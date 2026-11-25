"""More cars than chargers: the cars are a list of their own (settings["cars"]), and each charger knows which car is in it.

A car: {"id", "name", "soc" (its battery level, from the car's integration), "plug" (the car's own "plugged in"
sensor), "car_kwh", "target", "trip", "ready", "need_kwh"}. A car without Home Assistant has only a name and a size,
and charges "at most" kWh.

Which car is in a charger ("car" = charger 1, "car2", "car3" …), settings["car_in"]:
- picked by hand: it stays for that charge (settings["car_in_manual"]) and is forgotten when the car is unplugged;
- else the car whose own plug sensor says it is plugged in - a car whose binary sensor says it isn't, isn't;
- else, when it can't tell, by what the car takes: each car's steady charging power is learned from charges where
  the car was sure (picked by hand or told by its own sensor). A car in the charger for a few minutes is taken for
  the car whose power matches - only when every car it could be has 3 charges behind it and they lie clearly apart
  (3.7 kW against 11 kW, say);
- else the same car as last time (else the first car that can be in it).

With a car in it, the charger takes the car's level, target, trip, ready time and "at most"; without the list
nothing changes (the charger's own settings, as before).
"""

from __future__ import annotations

from statistics import median
from typing import Any
import uuid

CAR_FIELDS = ("soc", "car_kwh", "target", "trip", "ready", "need_kwh")
MIN_W = 1000  # charging (below: waiting, or the last trickle)
MIN_SESSIONS = 3  # charges a car needs behind it before its power tells it apart
MATCH = 0.15  # the power now within 15 % of the car's
APART = 0.30  # and every other car it could be at least 30 % away


def cars(settings: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in (settings.get("cars") or []) if isinstance(c, dict) and c.get("id")]


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def car_in(settings: dict[str, Any], part: str) -> dict[str, Any] | None:
    """The car in this charger (None without a list of cars)."""
    lst = cars(settings)
    if not lst:
        return None
    cid = (settings.get("car_in") or {}).get(part)
    return next((c for c in lst if c["id"] == cid), None) or lst[0]


def merged(settings: dict[str, Any], part: str, conf: dict[str, Any]) -> dict[str, Any]:
    """An extra charger's settings with the car in it laid over: its level sensor, size, target, trip, ready, at most."""
    car = car_in(settings, part)
    if car is None:
        return conf
    return {**conf, **{k: car.get(k) for k in CAR_FIELDS}, "car_id": car["id"], "car_name": car.get("name") or ""}


def _plugged(state: dict[str, Any] | None, entity: str) -> bool | None:
    """The car's own sensor: True plugged in, False surely not (a binary sensor that is off), None can't tell."""
    from .chargers import is_plugged

    s = str((state or {}).get("state") or "").strip().lower()
    if s in ("", "unknown", "unavailable", "none"):
        return None
    if is_plugged(s):
        return True
    return False if entity.startswith("binary_sensor.") else None


def car_kw(car: dict[str, Any]) -> float | None:
    """The car's steady charging power (kW), once it has MIN_SESSIONS charges behind it."""
    seen = [float(x) for x in car.get("kw_seen") or [] if isinstance(x, (int, float))]
    return round(median(seen), 1) if len(seen) >= MIN_SESSIONS else None


def by_power(lst: list[dict[str, Any]], ids: list[str], kw: float | None) -> str | None:
    """The one car (of ids) whose learned power matches kw - None unless it is clear."""
    if kw is None or not ids:
        return None
    learned = {i: car_kw(next(c for c in lst if c["id"] == i)) for i in ids}
    if any(v is None for v in learned.values()):
        return None  # a car it could be that hasn't been learned: no telling it out
    rel = sorted(((abs(kw - v) / v, i) for i, v in learned.items()))
    if rel[0][0] > MATCH or (len(rel) > 1 and rel[1][0] < APART):
        return None
    return rel[0][1]


class PowerWatch:
    """What each charger's car takes this charge (a sample each round while it charges): the power now for the
    guess, and the steady power when the car leaves - learned for the car only when it was sure which car it was."""

    def __init__(self) -> None:
        self.samples: dict[str, list[float]] = {}

    def see(self, plugged: dict[str, bool], watts: dict[str, float | None]) -> dict[str, float]:
        """One round. Returns the steady kW of the charges that just ended (at least 10 samples)."""
        done = {}
        for part, plug in plugged.items():
            if plug:
                w = watts.get(part)
                if w is not None and w >= MIN_W:
                    self.samples.setdefault(part, []).append(w / 1000)
            elif part in self.samples:
                s = sorted(self.samples.pop(part))
                if len(s) >= 10:
                    done[part] = round(s[int(0.9 * (len(s) - 1))], 2)  # the steady power, not the taper near full
        return done

    def now_kw(self, part: str) -> float | None:
        """The power this charge, after a few minutes of charging (the last samples' middle)."""
        s = self.samples.get(part) or []
        return round(median(s[-6:]), 2) if len(s) >= 4 else None


def learn(settings: dict[str, Any], done: dict[str, float]) -> dict[str, Any] | None:
    """Charges that ended: their power is kept for the car - only when it was sure which car it was."""
    sure = {**(settings.get("car_in_sure") or {}), **(settings.get("car_in_manual") or {})}
    lst = list(settings.get("cars") or [])
    changed = False
    for part, kw in done.items():
        car = car_in(settings, part)
        if car is None or not sure.get(part) or not 1 <= kw <= 50:
            continue
        lst = [{**c, "kw_seen": ([*(c.get("kw_seen") or []), kw])[-6:]} if c.get("id") == car["id"] else c for c in lst]
        changed = True
    return {"cars": lst} if changed else None


def assign(settings: dict[str, Any], states: dict[str, Any], plugged: dict[str, bool],
           kw_now: dict[str, float | None] | None = None) -> dict[str, Any] | None:
    """Which car is in each charger now (plugged: charger part -> a car in it; kw_now: what it takes this charge).
    The settings to save, or None."""
    lst = cars(settings)
    if not lst:
        return None
    was, manual = dict(settings.get("car_in") or {}), dict(settings.get("car_in_manual") or {})
    was_sure = dict(settings.get("car_in_sure") or {})
    now, man, sure_of = dict(was), dict(manual), dict(was_sure)
    say = {c["id"]: _plugged(states.get(c["plug"]), c["plug"]) if c.get("plug") else None for c in lst}
    taken: set[str] = set()
    for part in sorted(plugged, key=lambda p: (not man.get(p), p)):  # hand-picked first: their car is taken
        if not plugged[part]:
            man.pop(part, None)  # unplugged: the next car is found again
            sure_of.pop(part, None)
            continue
        if man.get(part) and now.get(part):
            taken.add(now[part])
            continue
        sure = [c["id"] for c in lst if say[c["id"]] is True and c["id"] not in taken]
        maybe = [c["id"] for c in lst if say[c["id"]] is not False and c["id"] not in taken]
        if len(sure) == 1:
            pick = sure[0]
            sure_of[part] = True  # told by the car itself: its power may be learned
        else:
            sure_of.pop(part, None)
            pick = by_power(lst, sure or maybe, (kw_now or {}).get(part))
            if pick is None:
                pick = now.get(part) if now.get(part) in (sure or maybe) else (sure or maybe or [None])[0]
        if pick:
            now[part] = pick
            taken.add(pick)
    ids = {c["id"] for c in lst}
    now = {p: c for p, c in now.items() if c in ids}
    if now == was and man == manual and sure_of == was_sure:
        return None
    return {"car_in": now, "car_in_manual": man, "car_in_sure": sure_of}


def pick(settings: dict[str, Any], part: str, car_id: str) -> dict[str, Any]:
    """A car picked by hand for a charger: it stays for this charge - and leaves any other charger it was "in"."""
    now = {p: c for p, c in (settings.get("car_in") or {}).items() if c != car_id}
    now[part] = car_id
    return {"car_in": now, "car_in_manual": {**(settings.get("car_in_manual") or {}), part: True}}


def update_car(settings: dict[str, Any], car_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    return {"cars": [{**c, **fields} if c.get("id") == car_id else c for c in settings.get("cars") or []]}


def view(settings: dict[str, Any], part: str) -> dict[str, Any] | None:
    """For the card and the companion: the car in this charger, whether it was picked by hand, and the choices."""
    car = car_in(settings, part)
    if car is None:
        return None
    return {"id": car["id"], "name": car.get("name") or "", "manual": bool((settings.get("car_in_manual") or {}).get(part)),
            "choices": [{"id": c["id"], "name": c.get("name") or ""} for c in cars(settings)]}

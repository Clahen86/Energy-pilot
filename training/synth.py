"""Made-up hourly lines (a few houses, some weeks) - for the training's self-test, never real data.

    python training/synth.py out.json"""
from datetime import date, timedelta
import json
import math
import random
import sys

random.seed(1)
days = []
for home, (base, car) in {"h1": (0.4, True), "h2": (0.6, False), "h3": (0.3, True), "h4": (0.5, False)}.items():
    for i in range(45):
        d = date(2026, 10, 1) + timedelta(days=i)
        hours = []
        for h in range(24):
            house = base + (1.0 if 17 <= h < 21 else 0) + (0.4 if 6 <= h < 8 else 0) + (0.3 if d.weekday() >= 5 else 0)
            house *= random.uniform(0.8, 1.2)
            sun = max(0.0, math.sin((h - 7) / 10 * math.pi)) * 1.5 * random.uniform(0.3, 1.0) if 7 <= h <= 17 else 0.0
            hours.append({"h": h, "house": [round(house * random.uniform(0.7, 1.3), 3), round(house, 3)],
                          "sun": [round(sun * random.uniform(0.6, 1.4), 3), round(sun, 3)], "soc": [None, 30 if h == 0 else None],
                          "price": 1.0 if h < 6 else 3.5 if 17 <= h < 21 else 2.0})
        days.append({"home": home, "day": d.isoformat(), "hours": hours, "kind": {"country": "DK", "battery_kwh": 10, "has": {"car": car}}})
json.dump(days, open(sys.argv[1], "w"))

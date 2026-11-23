"""Train shared models on all houses' hourly lines, and measure whether they beat each house's own forecast.

The house's use: one model for all houses, told each house's kind (country, battery size, car) and its own recent
level (its use at this hour the day before and over the last week). The sun: a correction of each house's own sun
forecast, learned from all of them (hour, month, country).

The last 7 days are kept out of the training and used as the test: for each of those hours the shared model's guess
and the house's own forecast (what its Energy Pilot said the day before) are set against what really happened.
Prints Markdown for the job summary - totals only, never a single house.

    python training/train.py data.json model_dir
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
import json
import os
import pickle
import sys

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor

TEST_DAYS = 7
MIN_ROWS = 500  # below this a shared model says nothing


def plausible_day(d: dict) -> bool:
    """The sensor guard: a day whose numbers can't be right (W read as kW, a stuck sensor, sun at night, a sign the
    wrong way round) is kept out - one broken home must not teach every other home something wrong."""
    hours = d.get("hours") or []
    house = [r["house"][1] for r in hours if r.get("house") and r["house"][1] is not None]
    sun = [(int(r["h"]), r["sun"][1]) for r in hours if r.get("sun") and r["sun"][1] is not None]
    if len(house) < 12:
        return False
    if any(v < 0 or v > 30 for v in house):  # an hour above 30 kWh in a home: a unit gone wrong
        return False
    if len(set(round(v, 3) for v in house)) <= 2:  # the same number all day: a stuck sensor
        return False
    if any(v < -0.05 or v > 50 for _h, v in sun):
        return False
    night = [v for h, v in sun if h <= 2 or h >= 23]
    if night and max(night) > 0.3:  # sun at night: not a sun sensor
        return False
    return True


FEATURES = ["h", "weekday", "month", "country", "battery_kwh", "car", "prev", "week"]
# The shared house model goes out to Energy Pilot only when it clearly beats the houses' own forecasts on held-out days
MIN_HOMES, MIN_TEST_DAYS, MIN_BETTER, MIN_WIN_SHARE, MAX_WORSE = 8, 5, 5.0, 0.6, 20.0


def export_hgb(model, countries: list[str]) -> dict:
    """The trained trees as plain arrays, so Energy Pilot can use them with plain Python - no pickle (a downloaded pickle
    would run code) and no scikit-learn version to match."""
    trees = []
    for pred in model._predictors:
        n = pred[0].nodes
        # thresholds at full precision: rounded, an hour right at a split went the other way than in scikit-learn
        trees.append({"f": [int(x) for x in n["feature_idx"]], "t": [float(x) for x in n["num_threshold"]],
                      "l": [int(x) for x in n["left"]], "r": [int(x) for x in n["right"]],
                      "m": [int(x) for x in n["missing_go_to_left"]], "leaf": [int(x) for x in n["is_leaf"]],
                      "v": [float(x) for x in n["value"]]})
    return {"schema": 1, "kind": "house", "features": FEATURES, "countries": countries,
            "base": float(np.ravel(model._baseline_prediction)[0]), "trees": trees}


def predict_json(m: dict, x: list) -> float:
    """The same walk Energy Pilot does (sharedmodel.py) - checked against scikit-learn before anything is published."""
    out = m["base"]
    for t in m["trees"]:
        i = 0
        while not t["leaf"][i]:
            v = x[t["f"][i]]
            go_left = t["m"][i] if v is None or v != v else v <= t["t"][i]
            i = t["l"][i] if go_left else t["r"][i]
        out += t["v"][i]
    return out


def data_countries(data: list[dict]) -> list[str]:
    return sorted({(d.get("kind") or {}).get("country") or "?" for d in data})


def rows_from(data: list[dict]) -> list[dict]:
    """One row per house and hour, with what is known the day before."""
    by_home: dict[str, dict[str, dict]] = defaultdict(dict)
    for d in data:
        if plausible_day(d):
            by_home[d["home"]][d["day"]] = d
    countries = data_countries(data)
    out = []
    for home, days in by_home.items():
        real: dict[tuple[str, int], float] = {}
        for day, d in days.items():
            for r in d.get("hours") or []:
                if r.get("house") and r["house"][1] is not None:
                    real[(day, int(r["h"]))] = float(r["house"][1])
        for day, d in days.items():
            k = d.get("kind") or {}
            dd = date.fromisoformat(day)
            for r in d.get("hours") or []:
                h = int(r["h"])
                if not r.get("house") or r["house"][1] is None:
                    continue
                prev = real.get(((dd - timedelta(days=1)).isoformat(), h))
                week = [real.get(((dd - timedelta(days=i)).isoformat(), h)) for i in range(1, 8)]
                week = [w for w in week if w is not None]
                if prev is None or not week:
                    continue  # the house's own recent level is needed
                sun = r.get("sun") or [None, None]
                out.append({
                    "home": home, "day": day, "h": h,
                    "x": [h, dd.weekday(), dd.month, countries.index(k.get("country") or "?"), float(k.get("battery_kwh") or 0),
                          1.0 if (k.get("has") or {}).get("car") else 0.0, prev, sum(week) / len(week)],
                    "y": float(r["house"][1]), "own": r["house"][0],
                    "sx": [h, dd.month, countries.index(k.get("country") or "?"), float(sun[0])] if sun[0] is not None else None,
                    "sy": float(sun[1]) if sun[1] is not None else None,
                })
    return out


def score(name: str, rows: list[dict], pred: np.ndarray, own_key: str, y_key: str) -> list[str]:
    own = np.array([r[own_key] for r in rows], dtype=float)
    y = np.array([r[y_key] for r in rows], dtype=float)
    mae_m, mae_o = float(np.mean(np.abs(pred - y))), float(np.mean(np.abs(own - y)))
    homes = defaultdict(lambda: [0.0, 0.0])
    for r, p, o, t in zip(rows, pred, own, y):
        homes[r["home"]][0] += abs(p - t)
        homes[r["home"]][1] += abs(o - t)
    wins = sum(1 for m, o in homes.values() if m < o)
    better = (mae_o - mae_m) / mae_o * 100 if mae_o else 0.0
    return [f"| {name} | {mae_o:.3f} kWh | {mae_m:.3f} kWh | {better:+.0f} % | {wins} af {len(homes)} |"], better, wins, len(homes)


def main() -> None:
    data = json.load(open(sys.argv[1]))
    model_dir = sys.argv[2]
    os.makedirs(model_dir, exist_ok=True)
    rows = rows_from(data)
    bad = [d for d in data if not plausible_day(d)]
    print("## Træning af fællesmodeller\n")
    print(f"{len({d['home'] for d in data})} huse, {len(data)} dage, {len(rows)} timer med det, der skal til.\n")
    if bad:
        print(f"Sensor-vagten holdt {len(bad)} dage fra {len({d['home'] for d in bad})} huse ude (tal, der ikke kan passe).\n")
    if len(rows) < MIN_ROWS:
        print(f"For lidt data endnu (mindst {MIN_ROWS} timer). Modellen trænes, når der er mere.")
        return
    last = max(r["day"] for r in rows)
    cut = (date.fromisoformat(last) - timedelta(days=TEST_DAYS)).isoformat()
    train = [r for r in rows if r["day"] <= cut]
    test = [r for r in rows if r["day"] > cut and r["own"] is not None]
    if len(train) < MIN_ROWS or len(test) < 50:
        print("For lidt data til både træning og test endnu.")
        return
    table = ["| | Husenes egne | Fællesmodel | Forskel | Bedre i |", "|---|---|---|---|---|"]
    # Small enough to hand out (about 100-150 KB as JSON) and to walk in plain Python every hour
    house = HistGradientBoostingRegressor(max_iter=150, learning_rate=0.08, max_leaf_nodes=15, min_samples_leaf=40).fit(
        [r["x"] for r in train], [r["y"] for r in train])
    lines, better, wins, n = score("Forbrug", test, house.predict([r["x"] for r in test]), "own", "y")
    table += lines
    result = {"house": {"better_pct": round(better, 1), "wins": wins, "homes": n}}
    s_train = [r for r in train if r["sx"] and r["sy"] is not None]
    s_test = [r for r in test if r["sx"] and r["sy"] is not None and (r["sx"][3] > 0.05 or r["sy"] > 0.05)]
    if len(s_train) >= MIN_ROWS and len(s_test) >= 50:
        sun = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.05).fit([r["sx"] for r in s_train], [r["sy"] for r in s_train])
        for r in s_test:
            r["sown"] = r["sx"][3]
        lines, sb, sw, sn = score("Sol", s_test, np.clip(sun.predict([r["sx"] for r in s_test]), 0, None), "sown", "sy")
        table += lines
        result["sun"] = {"better_pct": round(sb, 1), "wins": sw, "homes": sn}
        with open(os.path.join(model_dir, "sun.pkl"), "wb") as f:
            pickle.dump(sun, f)
    print("\n".join(table) + "\n")
    # Per home on the held-out days: none may be much worse with the shared model
    per = defaultdict(lambda: [0.0, 0.0])
    for r, p in zip(test, house.predict([r["x"] for r in test])):
        per[r["home"]][0] += abs(p - r["y"])
        per[r["home"]][1] += abs(r["own"] - r["y"])
    worst = max(((m - o) / o * 100 if o else 0.0) for m, o in per.values()) if per else 0.0
    test_days = len({r["day"] for r in test})
    ready = (n >= MIN_HOMES and test_days >= MIN_TEST_DAYS and better >= MIN_BETTER and wins >= MIN_WIN_SHARE * n
             and worst <= MAX_WORSE)
    print("✅ Fællesmodellen for forbrug rammer klart bedre - den sendes ud til Energipilot." if ready else
          f"⏳ Fællesmodellen udgives ikke endnu ({n} huse, {test_days} testdage, {better:+.0f} %, værste hus {worst:+.0f} %).")
    if ready or os.environ.get("EP_EXPORT_ALWAYS") == "1":  # (the workflow's self-test on made-up data checks the export)
        try:
            exp = export_hgb(house, data_countries(data))
        except Exception as err:  # noqa: BLE001 - scikit-learn's inner layout changed: nothing goes out
            print(f"⚠️ Eksporten kunne ikke laves ({type(err).__name__}: {err}) - intet udgivet.")
            return
        sample = [r["x"] for r in test[:200]]
        ref = house.predict(sample)
        diff = max((abs(predict_json(exp, x) - y) for x, y in zip(sample, ref)), default=0.0)
        if diff > 1e-4:
            print(f"⚠️ Eksporten regner ikke som modellen (op til {diff:.4g} kWh fra) - intet udgivet.")
        else:
            body = json.dumps({**exp, "probe": [[x, round(float(y), 6)] for x, y in zip(sample[:20], ref[:20])],
                               "trained": last, "homes": n, "test_days": test_days, "better_pct": round(better, 1),
                               "wins": wins, "clip": 1.5}, separators=(",", ":"))
            import hashlib
            exp_sha = hashlib.sha256(body.encode()).hexdigest()
            with open(os.path.join(model_dir, "house.json"), "w") as f:
                f.write(body)
            print(f"Eksport: {len(body) // 1024} KB, sha {exp_sha[:12]}.")
    with open(os.path.join(model_dir, "house.pkl"), "wb") as f:
        pickle.dump(house, f)
    with open(os.path.join(model_dir, "result.json"), "w") as f:
        json.dump({**result, "ready": ready, "rows": len(rows)}, f)


if __name__ == "__main__":
    main()

"""The nightly reports to the developer - issues on GitHub, never anything sent to the users:

- A profile draft: an integration Energy Pilot has no profile for, used by at least three homes - its controls and
  sensors as those homes have them (names with the user's own words taken out), as a start for a profile.
- A failure pattern: a test step that fails for the same profile in at least two homes.

    python training/reports.py setups.json tests.json out.json
Writes [{"title", "body"}] - the workflow opens each as an issue unless one with that title is open already."""
from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

DRAFT_HOMES = 2  # an issue to the developer only - two homes are enough to start a profile from
FAIL_HOMES = 2
# Built by the user, or firmware for many kinds of devices: no one brand to make a profile for
HOMEMADE = {"template", "mqtt", "modbus", "rest", "command_line", "esphome"}


def _known() -> tuple[set[str], set[str]]:
    """The integrations Energy Pilot has a profile for, and the ones that are never a home battery (cars, alarms,
    cameras, heating) - from the app's own lists, so the report follows the app."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "energy_pilot"))
        from energy_pilot import adapters, detect

        profiles = set(adapters.PROFILES) | {p["platform"] for p in adapters.PROFILES.values() if p.get("platform")}
        never = set(detect.CAR_PLATFORMS) | set(detect.NOT_HOME_BATTERY)
    except Exception:  # noqa: BLE001 - the report still comes, only less tidy
        profiles, never = set(), set()
    never |= {"aarlo", "blink", "skoda", "byd_vehicle", "gwm_ora", "myskoda", "ha_washdata", "netatmo"}
    return profiles, never - profiles


PROFILED, NOT_BATTERY = _known()


def drafts(setups: list[dict]) -> list[dict]:
    homes: dict[str, set] = defaultdict(set)
    ents: dict[str, Counter] = defaultdict(Counter)
    makers: dict[str, Counter] = defaultdict(Counter)
    for r in setups:
        for d in r.get("devices") or []:
            if d.get("kind") != "battery" or d.get("profile") or not d.get("platform"):
                continue
            plat = d["platform"]
            if plat in NOT_BATTERY:
                continue  # a car's, a camera's or a thermostat's battery - not a home battery
            homes[plat].add(r["home"])
            for e in d.get("entities") or []:
                if e.get("platform") == plat:  # its own entities only - not a solar forecast or a price beside it
                    ents[plat][(str(e.get("name")), str(e.get("use")), str(e.get("unit") or ""))] += 1
    out = []
    # One overview of every brand without a profile (a single issue, made once) - which ones are worth a profile next
    brands = sorted(((len(hs), p) for p, hs in homes.items() if p not in HOMEMADE and p not in PROFILED), reverse=True)
    # A profile exists, but these homes have none picked: read only (a cloud integration), or its controls missing
    unpicked = sorted(((len(hs), p) for p, hs in homes.items() if p in PROFILED), reverse=True)
    if brands or unpicked:
        table = "\n".join(f"| `{p}` | {n} |" for n, p in brands) or "| – | |"
        table2 = "\n".join(f"| `{p}` | {n} |" for n, p in unpicked) or "| – | |"
        out.append({"title": f"⚡ Integrations without a profile: {len(brands)} brands, {sum(n for n, _ in brands)} homes",
                    "body": "Battery integrations Energy Pilot has no profile for, by homes (last 30 days):\n\n"
                            f"| Integration | Homes |\n|---|---|\n{table}\n\nA draft issue follows by itself when two homes use one.\n\n"
                            "Has a profile, but these homes have none in use (read only, or its controls are missing):\n\n"
                            f"| Integration | Homes |\n|---|---|\n{table2}\n\n"
                            "Cars, cameras and thermostats are left out.\n\n"
                            "_Made by the nightly training (training/reports.py). A new one comes when the list changes._"})
    for plat, hs in homes.items():
        if len(hs) < DRAFT_HOMES or plat in HOMEMADE or plat in PROFILED:
            continue
        common = [(n, u, unit, c) for (n, u, unit), c in ents[plat].most_common() if c >= 2][:40]
        lines = "\n".join(f"| `{n}` | {u} | {unit} | {c} |" for n, u, unit, c in common)
        out.append({"title": f"⚡ Profile draft: {plat} ({len(hs)} homes without a profile)",
                    "body": f"{len(hs)} installations use the integration `{plat}` and Energy Pilot has no profile for it.\n\n"
                            f"What at least two of them have:\n\n| Entity | Used for | Unit | Homes |\n|---|---|---|---|\n{lines}\n\n"
                            "_Made by the nightly training (training/reports.py). Names have the user's own words taken out._"})
    return out


def _ver(v: str | None) -> tuple:
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return ()


def failures(tests: list[dict]) -> list[dict]:
    seen: dict[tuple, int] = Counter()
    newest: dict[tuple, tuple] = {}
    kinds: dict[tuple, Counter] = defaultdict(Counter)
    total: dict[tuple, int] = Counter()
    for t in tests:
        key = (t.get("part"), t.get("profile"))
        total[key] += 1
        for item in str(t.get("failed") or "").split(","):
            if not item:
                continue
            item, _, kind = item.partition("@")
            step, _, why = item.partition(":")
            k = key + (step, why)
            seen[k] += 1
            if kind:
                kinds[k][kind] += 1
            if _ver(t.get("version")) > newest.get(k, ()):
                newest[k] = _ver(t.get("version"))
    out = []
    for (part, prof, step, why), n in seen.items():
        if n < FAIL_HOMES or not prof:
            continue
        k = (part, prof, step, why)
        last = ".".join(map(str, newest.get(k, ()))) or "?"
        what = ", ".join(f"`{c}` ({m})" for c, m in kinds[k].most_common(5))
        out.append({"title": f"⚡ Test fails: {prof} · {part} · {step} ({why or 'failed'})", "version": last,
                    "body": f"The self-test step **{step}** fails for `{prof}` ({part}) in {n} of {total[(part, prof)]} homes "
                            f"(last 60 days), reason: `{why or '?'}`.\n\n"
                            + (f"Details: {what}\n\n" if what else "")
                            + f"Last seen in version: {last}\n\n"
                            "_Made by the nightly training (training/reports.py). Closed, it comes back only if the fault "
                            "is seen in a newer version._"})
    return out


def to_open(issues: list[dict], known: list[dict]) -> list[dict]:
    """Which issues to open: none whose title is open already; one that was closed only when the fault has been
    seen in a newer version than the one the closed issue named (the fix didn't hold)."""
    import re

    out = []
    for i in issues:
        same = [k for k in known if k.get("title") == i["title"]]
        if any(k.get("state", "").upper() == "OPEN" for k in same):
            continue
        closed_v = [m.group(1) for k in same if (m := re.search(r"Last seen in version: ([0-9.]+)", k.get("body") or ""))]
        if same and (not closed_v or not i.get("version") or _ver(i["version"]) <= max(_ver(v) for v in closed_v)):
            continue  # closed: handled - unless the fault is seen in a newer version than the closed issue named
        out.append(i)
    return out


def main() -> None:
    setups = json.load(open(sys.argv[1]))
    tests = json.load(open(sys.argv[2]))
    issues = drafts(setups) + failures(tests)
    known = []
    if len(sys.argv) > 4:
        try:
            known = json.load(open(sys.argv[4]))
        except (OSError, ValueError):
            known = []
    issues = to_open(issues, known)
    json.dump(issues, open(sys.argv[3], "w"))
    print(f"## Rapporter\n\n{len(issues)} nye issues (profiludkast og fejlmønstre) - kendte og lukkede springes over.")


if __name__ == "__main__":
    main()

"""The nightly reports to the developer - issues on GitHub, never anything sent to the users:

- A profile draft: an integration Energy Pilot has no profile for, used by at least three homes - its controls and
  sensors as those homes have them (names with the user's own words taken out), as a start for a profile.
- A failure pattern: a test step that fails for the same profile in at least two homes.

    python training/reports.py setups.json tests.json out.json
Writes [{"title", "body"}] - the workflow opens each as an issue unless one with that title is open already."""
from __future__ import annotations

from collections import Counter, defaultdict
import json
import sys

DRAFT_HOMES = 3
FAIL_HOMES = 2


def drafts(setups: list[dict]) -> list[dict]:
    homes: dict[str, set] = defaultdict(set)
    ents: dict[str, Counter] = defaultdict(Counter)
    makers: dict[str, Counter] = defaultdict(Counter)
    for r in setups:
        for d in r.get("devices") or []:
            if d.get("kind") != "battery" or d.get("profile") or not d.get("platform"):
                continue
            plat = d["platform"]
            homes[plat].add(r["home"])
            for e in d.get("entities") or []:
                ents[plat][(str(e.get("name")), str(e.get("use")), str(e.get("unit") or ""))] += 1
    out = []
    for plat, hs in homes.items():
        if len(hs) < DRAFT_HOMES:
            continue
        common = [(n, u, unit, c) for (n, u, unit), c in ents[plat].most_common() if c >= 2][:40]
        lines = "\n".join(f"| `{n}` | {u} | {unit} | {c} |" for n, u, unit, c in common)
        out.append({"title": f"⚡ Profile draft: {plat} ({len(hs)} homes without a profile)",
                    "body": f"{len(hs)} installations use the integration `{plat}` and Energy Pilot has no profile for it.\n\n"
                            f"What at least two of them have:\n\n| Entity | Used for | Unit | Homes |\n|---|---|---|---|\n{lines}\n\n"
                            "_Made by the nightly training (training/reports.py). Names have the user's own words taken out._"})
    return out


def failures(tests: list[dict]) -> list[dict]:
    seen: dict[tuple, int] = Counter()
    total: dict[tuple, int] = Counter()
    for t in tests:
        key = (t.get("part"), t.get("profile"))
        total[key] += 1
        for step in str(t.get("failed") or "").split(","):
            if step:
                seen[key + (step.split(":")[0], step.split(":", 1)[1] if ":" in step else "")] += 1
    out = []
    for (part, prof, step, why), n in seen.items():
        if n >= FAIL_HOMES and prof:
            out.append({"title": f"⚡ Test fails: {prof} · {part} · {step} ({why or 'failed'})",
                        "body": f"The self-test step **{step}** fails for `{prof}` ({part}) in {n} of {total[(part, prof)]} homes "
                                f"(last 60 days), reason: `{why or '?'}`.\n\n_Made by the nightly training (training/reports.py)._"})
    return out


def main() -> None:
    setups = json.load(open(sys.argv[1]))
    tests = json.load(open(sys.argv[2]))
    issues = drafts(setups) + failures(tests)
    json.dump(issues, open(sys.argv[3], "w"))
    print(f"## Rapporter\n\n{len(issues)} mulige issues (profiludkast og fejlmønstre).")


if __name__ == "__main__":
    main()

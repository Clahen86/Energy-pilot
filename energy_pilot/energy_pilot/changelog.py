"""What changed between versions - from CHANGELOG.md (shipped with the app, and the newest one on GitHub).

Used for "What's new" after an update and for the update card before one, so a user sees the changes of every
version they skip, not just the last.
"""

from __future__ import annotations

import os
import re
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL = (os.environ.get("CHANGELOG_PATH") or "/app/CHANGELOG.md", os.path.join(HERE, "..", "CHANGELOG.md"))
REMOTE = "https://raw.githubusercontent.com/Clahen86/Energy-pilot/main/energy_pilot/CHANGELOG.md"
HEAD = re.compile(r"^##\s+v?(\d+(?:\.\d+){1,3})(?:\s+[–-]\s+(\S+))?\s*$")


def ver(v: Any) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return (0,)


def parse(text: str) -> list[dict[str, Any]]:
    """[{"version", "date", "items"}], newest first, as in the file. "Unreleased" is left out."""
    out: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for line in (text or "").splitlines():
        m = HEAD.match(line.strip())
        if m:
            cur = {"version": m.group(1), "date": m.group(2) or "", "items": []}
            out.append(cur)
        elif line.startswith("## "):
            cur = None
        elif cur is not None and line.startswith("- "):
            cur["items"].append(line[2:].strip())
    return out


def between(sections: list[dict[str, Any]], after: str, upto: str, most: int = 8, items: int = 6) -> list[dict[str, Any]]:
    """The versions after `after` up to and including `upto`, newest first - at most `most`, each cut to `items` lines."""
    lo, hi = ver(after), ver(upto)
    picked = [s for s in sections if lo < ver(s["version"]) <= hi]
    picked.sort(key=lambda s: ver(s["version"]), reverse=True)
    return [{**s, "items": s["items"][:items], "more": max(0, len(s["items"]) - items)} for s in picked[:most]]


_local: list[dict[str, Any]] | None = None


def local() -> list[dict[str, Any]]:
    global _local
    if _local is None:
        _local = []
        for path in LOCAL:
            try:
                with open(path, encoding="utf-8") as f:
                    _local = parse(f.read())
                break
            except OSError:
                continue
    return _local

"""What's new: versions between the one before and now, from CHANGELOG.md."""

from energy_pilot import changelog

TEXT = """# Changelog

## Unreleased

- Not out yet

## 0.92.1 – 2026-11-19

- Text fix

## 0.92.0 – 2026-11-18

- Says why
- Never sells at a loss

## 0.91.0 – 2026-11-18

- Machines
"""


def test_parse_leaves_out_unreleased():
    s = changelog.parse(TEXT)
    assert [x["version"] for x in s] == ["0.92.1", "0.92.0", "0.91.0"]
    assert s[1]["items"] == ["Says why", "Never sells at a loss"] and s[0]["date"] == "2026-11-19"


def test_between_skipped_versions_newest_first():
    got = changelog.between(changelog.parse(TEXT), "0.91.0", "0.92.1")
    assert [x["version"] for x in got] == ["0.92.1", "0.92.0"]
    assert changelog.between(changelog.parse(TEXT), "0.92.1", "0.92.1") == []


def test_the_shipped_changelog_reads():
    import os

    path = os.path.join(os.path.dirname(__file__), "..", "energy_pilot", "CHANGELOG.md")
    with open(path, encoding="utf-8") as f:
        s = changelog.parse(f.read())
    assert len(s) > 100 and s[0]["items"]

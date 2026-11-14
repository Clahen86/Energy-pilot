"""A comment from the developer gives one notification - not again on the next fetch, nor when the issue is closed."""

import asyncio
from types import SimpleNamespace

from energy_pilot import telemetry


class Ov:
    def __init__(self):
        self.settings = {"install_id": "a" * 32}
        self.calls = []
        self.ha = SimpleNamespace(config={"language": "en"}, call_service=self._call)

    async def _call(self, *a):
        self.calls.append(a)

    def save(self, d):
        self.settings.update(d)


def test_one_notification_per_comment(monkeypatch):
    ov = Ov()
    t = telemetry.Telemetry(ov, "https://x")
    answer = {"reports": [], "notes": [{"error": "E", "msgs": [{"from": "dev", "text": "Fixed in 0.71.1", "t": "2026-11-14T08:00:00Z"}]}]}

    async def ask(path, body):
        return answer

    monkeypatch.setattr(t, "_ask", ask)
    asyncio.run(t.fetch_answers())
    assert len(ov.calls) == 1
    asyncio.run(t.fetch_answers())
    answer["reports"] = [{"id": "r", "state": "closed", "msgs": []}]
    asyncio.run(t.fetch_answers())
    assert len(ov.calls) == 1
    answer["notes"][0]["msgs"].append({"from": "dev", "text": "One more", "t": "2026-11-15T08:00:00Z"})
    asyncio.run(t.fetch_answers())
    assert len(ov.calls) == 2


def test_close_hides_until_a_new_comment():
    ov = Ov()
    t = telemetry.Telemetry(ov, "https://x")
    ov.settings["replies"] = {"reports": [{"id": "r1", "state": "open", "msgs": [{"from": "dev", "text": "hi", "t": "2026-11-14T08:00:00Z"}]}], "notes": []}
    assert len(t.visible()["reports"]) == 1
    t.hide("r1")
    assert t.visible()["reports"] == []
    ov.settings["replies"]["reports"][0]["msgs"].append({"from": "dev", "text": "more", "t": "2026-11-15T08:00:00Z"})
    assert len(t.visible()["reports"]) == 1


def test_closed_issue_goes_after_a_week_and_seen_after_two(monkeypatch):
    ov = Ov()
    t = telemetry.Telemetry(ov, "https://x")
    msg = {"from": "dev", "text": "fixed", "t": "2026-11-01T08:00:00Z"}
    ov.settings["replies"] = {"reports": [], "notes": [{"error": "E", "state": "closed", "closed_at": "2026-11-02T08:00:00Z", "msgs": [msg]},
                                                       {"error": "F", "state": "open", "msgs": [dict(msg)]}]}
    now = 1794700000.0  # 2026-11-15
    monkeypatch.setattr(telemetry.time, "time", lambda: now)
    vis = t.visible(mark_seen=True)["notes"]
    assert [n["error"] for n in vis] == ["F"]  # closed 13 days ago
    now += 15 * 86400
    assert t.visible()["notes"] == []  # seen more than two weeks ago

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

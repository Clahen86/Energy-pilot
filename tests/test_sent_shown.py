import asyncio

from energy_pilot.telemetry import Telemetry


class O:
    def __init__(self):
        self.settings = {"share_anonymous": False}
        self.ha = type("H", (), {"config": {}})()

    def save(self, d):
        self.settings.update(d)


def test_sent_message_shown_until_github_lists_it():
    t = Telemetry.__new__(Telemetry)
    t.ov, t.url = O(), "x"
    lists = [[], [{"from": "you", "text": "hello", "t": "2026-11-16T10:00:00Z"}]]

    async def ask(path, body):
        if path == "/reply":
            return {"ok": True}
        return {"reports": [{"id": "r1", "msgs": list(lists.pop(0))}]}
    t._ask = ask
    assert asyncio.run(t.write_back("r1", "hello"))["ok"]
    msgs = t.ov.settings["replies"]["reports"][0]["msgs"]
    assert [m["text"] for m in msgs] == ["hello"]  # GitHub didn't list it yet - shown anyway
    asyncio.run(t.fetch_answers(notify=False))
    assert len(t.ov.settings["replies"]["reports"][0]["msgs"]) == 1 and t._sent == []

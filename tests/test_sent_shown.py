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


def test_reply_with_pictures_and_the_question_shown():
    t = Telemetry.__new__(Telemetry)
    t.ov, t.url = O(), "x"
    t.ov.settings["report_notes"] = {"r1": "Why does it charge at noon?"}
    sent = {}

    async def ask(path, body):
        if path == "/reply":
            sent.update(body)
            return {"ok": True}
        return {"reports": [{"id": "r1", "msgs": [{"from": "dev", "text": "hi", "t": "2026-11-16T09:00:00Z"}]}]}
    t._ask = ask
    assert asyncio.run(t.write_back("r1", "", [{"name": "a", "data": "eA=="}]))["ok"]
    assert sent["images"] == [{"name": "a", "data": "eA=="}]
    r = t.visible()["reports"][0]
    assert r["question"] == "Why does it charge at noon?"
    assert r["msgs"][-1]["pics"] == 1

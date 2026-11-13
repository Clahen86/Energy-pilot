"""Learning together: only anonymous lines, off when the user says so, and a fix 3 others found is used here."""

import asyncio
import logging
from types import SimpleNamespace

from energy_pilot import control as C
from energy_pilot import telemetry as T


def ov(settings=None):
    store = dict(settings or {})
    return SimpleNamespace(settings=store, save=lambda d: store.update(d),
                           ha=SimpleNamespace(states={}, config={"country": "DK", "currency": "DKK", "version": "2026.11.1"})), store


def test_off_sends_nothing_and_an_install_gets_a_random_id():
    o, store = ov({"share_anonymous": False})
    t = T.Telemetry(o, "https://x.example")
    assert len(store["install_id"]) == 32 and not t.on
    sent = []
    t._post = lambda kind, payload: sent.append(kind)
    t.event("test", {})
    assert sent == []


def test_the_daily_line_holds_nothing_personal():
    o, store = ov({"language": "da", "battery_export": True})
    o.flow = lambda: {"has": {"battery": True, "pv": True}}
    o.source = lambda r: "integration:stromligning"
    o.role = lambda r: "sensor.x"
    o.controller = SimpleNamespace(mode=lambda p: "control", parts=lambda: ["battery"], profile_key=lambda p: "growatt",
                                   model="SPH", platforms={"car": "keba"})
    d = T.Telemetry(o, "https://x.example").daily()
    assert d["price"] == "stromligning" and d["profile"] == "growatt" and d["country"] == "DK"
    text = str(d)
    assert "sensor." not in text and "entity" not in text  # no entity names, no readings hour by hour


def test_an_error_is_sent_once_a_day_without_its_message():
    o, _ = ov()
    t = T.Telemetry(o, "https://x.example")
    got = []
    t.event = lambda kind, p: got.append(p)
    try:
        raise ValueError("select.claus_inverter refused")
    except ValueError:
        import sys
        rec = logging.LogRecord("energy_pilot.engine", logging.WARNING, __file__, 1, "x", None, sys.exc_info())
    t.error(rec)
    t.error(rec)
    assert len(got) == 1 and "claus" not in got[0]["text"] and got[0]["text"].startswith("ValueError")


def test_a_shared_fix_is_used_only_when_the_inverter_offers_it_and_can_be_undone():
    c = C.Controller.__new__(C.Controller)
    store = {"community": {"fixes": [{"profile": "solarman", "intent": "export", "from": "Sell First", "to": "Selling First"}]}}
    c.ov = SimpleNamespace(settings=store)
    c.ha = SimpleNamespace(states={"select.inv_mode": {"attributes": {"options": ["Selling First", "Zero Export"]}}})
    c.profile_key = lambda *a: "solarman"
    call = {"domain": "select", "service": "select_option", "data": {"entity_id": "select.inv_mode", "option": "Sell First"}}
    assert c._fixed("battery", "export", [call])[0]["data"]["option"] == "Selling First"
    assert "export|Sell First|Selling First" in c.community_used
    store["community_ignore"] = ["export|Sell First|Selling First"]
    assert c._fixed("battery", "export", [call])[0]["data"]["option"] == "Sell First"
    store["community_ignore"] = []
    c.ha.states["select.inv_mode"]["attributes"]["options"] = ["Zero Export"]
    assert c._fixed("battery", "export", [call])[0]["data"]["option"] == "Sell First"  # not offered here

"""Test your system: steps pass only when the battery really does it, a wrong option is mended by trying the
control's other safe options, and everything is put back afterwards."""

import asyncio
from types import SimpleNamespace

from energy_pilot import control as C
from energy_pilot import selftest as S

SEL = "select.inv_work_mode"
NUM = "number.inv_power"


class FakeInverter:
    """A select whose option decides what the battery does; 'works' maps option -> battery W."""

    def __init__(self, works, options):
        self.states = {SEL: {"state": "Self Use", "attributes": {"options": options}}, NUM: {"state": "3000", "attributes": {}}}
        self.works = works
        self.sent = []

    async def call_service(self, domain, service, data):
        self.sent.append(dict(data))
        e = data["entity_id"]
        self.states[e]["state"] = str(data.get("option", data.get("value")))

    def flow(self):
        b = self.works.get(self.states[SEL]["state"], 0)
        return {"battery": b, "grid": b, "soc": 50, "has": {"battery": True}, "ev": None, "plug": False}


def make(works, options, steps):
    inv = FakeInverter(works, options)
    store = {"battery_export": True}
    ov = SimpleNamespace(settings=store, save=lambda d: store.update(d), flow=inv.flow)
    c = C.Controller.__new__(C.Controller)
    c.ha, c.ov = SimpleNamespace(states=inv.states, call_service=inv.call_service), ov
    c.entities, c.platforms, c.last, c.testing = {"battery": [SEL, NUM], "car": []}, {"battery": "x", "car": None}, {}, set()
    c.model = None
    c.profile_key = lambda *a: "custom"
    c.profile_steps = lambda *a: steps
    c._pool = lambda *a: [SEL, NUM]
    c.intents = lambda: {}
    t = S.SelfTest(c, ov)
    return t, inv, store


def run(t, parts=("battery",)):
    S.SAMPLE_S, S.STEADY_S, S.MIN_S = 0, 0, 0
    S.WAIT_S.update(local=0.05, cloud=0.05, car=0.05)
    orig = asyncio.sleep

    async def go():
        C.asyncio.sleep = S.asyncio.sleep = lambda *_a: orig(0.001)
        try:
            assert t.start(list(parts))
            await t._task
        finally:
            C.asyncio.sleep = S.asyncio.sleep = orig
    asyncio.run(go())


STEPS = {"normal": [(r"select\..*work_mode$", "select", "Self Use")],
         "hold": [(r"select\..*work_mode$", "select", "Battery Hold")],
         "charge": [(r"select\..*work_mode$", "select", "Force Charge"), (r"number\..*power$", "number", "{power_w}")],
         "export": [(r"select\..*work_mode$", "select", "Force Discharge")]}
OPTS = ["Self Use", "Battery Hold", "Force Charge", "Force Discharge", "Off-Grid"]


def test_all_steps_pass_and_everything_is_put_back():
    t, inv, store = make({"Self Use": 0, "Battery Hold": 0, "Force Charge": 900, "Force Discharge": -800}, OPTS, STEPS)
    run(t)
    res = {r["step"]: r["result"] for r in store["selftest"]["results"]}
    assert res == {"hold": "ok", "charge": "ok", "export": "ok", "normal": "ok"}
    assert inv.states[SEL]["state"] == "Self Use" and inv.states[NUM]["state"] == "3000"  # back as it was
    assert any(d.get("value") == 1000 for d in inv.sent)  # at most 1 kW
    assert t.status()["report_url"].startswith("https://github.com/Clahen86/Energy-pilot/issues/new?")


def test_a_wrong_option_is_mended_and_kept_but_never_an_unsafe_one():
    # This inverter charges on "Grid Charge", not on "Force Charge" - and "Off-Grid" must never be tried.
    opts = ["Self Use", "Battery Hold", "Force Charge", "Force Discharge", "Off-Grid", "Grid Charge"]
    t, inv, store = make({"Grid Charge": 900, "Force Discharge": -800, "Off-Grid": 900}, opts, STEPS)
    run(t)
    charge = next(r for r in store["selftest"]["results"] if r["step"] == "charge")
    assert charge["result"] == "fixed" and charge["option_to"] == "Grid Charge"
    assert not any(d.get("option") == "Off-Grid" for d in inv.sent)
    assert store["profile_fixes"]["battery"]["charge"][SEL]["to"] == "Grid Charge"
    # the controller now uses it in normal running
    calls = t.ctl.calls("battery", {"intent": "charge", "ctx": {**S._ctx_defaults()}})
    assert calls[0]["data"]["option"] == "Grid Charge"
    t.undo("battery", "charge", SEL)
    assert t.ctl.calls("battery", {"intent": "charge", "ctx": {**S._ctx_defaults()}})[0]["data"]["option"] == "Force Charge"


def test_a_cut_short_test_puts_the_settings_back_after_a_restart():
    t, inv, store = make({}, OPTS, STEPS)
    store["selftest"] = {"saved": {SEL: "Self Use", NUM: "3000"}}
    inv.states[SEL]["state"], inv.states[NUM]["state"] = "Force Charge", "1000"  # left mid-test
    orig = asyncio.sleep
    C.asyncio.sleep = lambda *_a: orig(0)
    try:
        asyncio.run(t.recover())
    finally:
        C.asyncio.sleep = orig
    assert inv.states[SEL]["state"] == "Self Use" and inv.states[NUM]["state"] == "3000"
    assert store["selftest"]["saved"] == {}

""""Car first" with a charger that follows the sun by itself (a Zappi on Eco+): the battery keeps the sun out, so the
surplus shows on the grid and the charger takes it - and gives it back when the car takes nothing."""

from test_import_limit_live import _ctl


def _sun(style="car_first", car_mode="shadow", plug=True, ev_w=0.0, soc=50, target=80, pv=4000):
    c = _ctl(500, limit=None)
    c.engine.result = {"battery": {"steps": [{"t": "2026-11-27T12:00:00+00:00", "action": "normal", "soc": 60, "grid": -2.0}],
                                   "slot_min": 60, "target": 60}}
    c.ov.flow = lambda: {"soc": 50, "house": 500, "pv": pv, "ev": ev_w, "plug": plug}
    c.ov.settings = {"inverter_profile": "victron", "style": style}
    c.ov.ev = lambda: {"soc": soc, "target": target}
    c.mode = lambda part: car_mode
    return c


def _battery(c):
    ev = c.ov.ev
    c._sun_to_car = lambda f, _s=c._sun_to_car: _s(f)
    want = c._sun_to_car(c.ov.flow())
    c.ov.ev = lambda: None  # the car's own part is left out here
    c._sun_to_car = lambda f: want
    b = c.intents()["battery"]
    c.ov.ev = ev
    return b


def test_the_battery_leaves_the_sun_to_the_car():
    b = _battery(_sun())
    assert b["intent"] == "hold" and b["ctx"]["max_charge_w"] == 0 and b["ctx"]["sun_car"]


def test_only_when_it_fits():
    for kw in ({"style": "cheapest"}, {"car_mode": "control"}, {"plug": False}, {"soc": 80}, {"pv": 1500}):
        b = _battery(_sun(**kw))
        assert not b["ctx"].get("sun_car") and b["intent"] == "normal", kw


def test_a_car_that_takes_nothing_gives_the_sun_back():
    c = _sun()
    f = c.ov.flow()
    assert c._sun_to_car(f, now=0) and c._sun_to_car(f, now=600)
    assert not c._sun_to_car(f, now=1000)  # 15 minutes and nothing taken: the battery gets the sun again
    assert not c._sun_to_car(f, now=2000)  # and keeps it for an hour
    assert c._sun_to_car(f, now=1000 + 3601)
    taking = {**f, "ev": 3000}
    assert c._sun_to_car(taking, now=5000) and c._sun_to_car(taking, now=8000)  # charging: it goes on

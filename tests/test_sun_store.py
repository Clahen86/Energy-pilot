"""Why the sun goes into the battery instead of being sold: it is worth more later (sold or used) than selling now."""

from datetime import datetime, timezone
from types import SimpleNamespace

from energy_pilot.overview import Overview

UTC = timezone.utc


def t(h, m=0):
    return datetime(2026, 11, 19, h, m, tzinfo=UTC)


def ov(steps, sells, sell=True):
    o = Overview.__new__(Overview)
    o.settings = {"sell": sell, "sell_price": 0}
    o.ha = SimpleNamespace(config={"time_zone": "UTC"})
    eng = SimpleNamespace(result={"battery": {"steps": steps, "slot_min": 30}}, settings=lambda: SimpleNamespace(efficiency=0.8))
    eng.sell_prices = lambda: sells
    eng.sell_at = lambda prices, when, fixed: prices[max(k for k in prices if k <= when)] if prices else fixed
    o.engine = eng
    return o


SELLS = {t(12): 0.185, t(16): 0.267, t(19): 0.21}
STEPS = [{"t": t(12, 30).isoformat(), "action": "discharge"}] + [
    {"t": t(h, m).isoformat(), "action": "export"} for h in (16, 17, 18) for m in (0, 30)]
PLAN = {"hours": [{"t": t(h).isoformat(), "price": 0.267} for h in range(12, 20)]}
SUN = {"pv": 1000, "house": 740, "battery": 220}


def test_stored_sun_is_sold_dearer_later():
    s = ov(STEPS, SELLS).sun_store(SUN, PLAN, now=t(12, 24))
    assert s and s["now"] == 0.185 and s["p"] == 0.267
    assert s["from"] == t(16).isoformat() and s["to"] == t(19).isoformat()  # sold 16-19 (the lone 12:30 slot is not shown)


def test_nothing_to_explain():
    assert ov(STEPS, SELLS).sun_store({"pv": 300, "house": 700, "battery": -400}, PLAN, now=t(12, 24)) is None  # not storing
    assert ov(STEPS, SELLS, sell=False).sun_store(SUN, PLAN, now=t(12, 24)) is None  # no selling
    flat = {t(12): 0.25}
    assert ov(STEPS, flat).sun_store(SUN, {"hours": []}, now=t(12, 24)) is None  # 0.25 * 0.8 is less than selling now

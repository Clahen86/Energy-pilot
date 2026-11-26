"""A fee on selling (the supplier's fee, the grid's feed-in tariff) is taken off every sell price - as Predbat's
rates_export_override with rate_increment: -9 does."""

import pytest

from energy_pilot.engine import Engine


def engine(settings, states=None, role=None):
    eng = Engine.__new__(Engine)
    eng.ha = type("H", (), {"config": {"country": "DK", "time_zone": "Europe/Copenhagen"}, "states": states or {}})()
    eng.ov = type("O", (), {"settings": settings, "role": lambda self, r: role if r == "sell_price" else None})()
    return eng


def test_fee_off_the_sensor_price():
    eng = engine({"sell": True, "sell_fee": 0.09}, {"sensor.export": {"state": "2.633", "attributes": {}}}, "sensor.export")
    assert [round(v, 3) for v in eng.sell_prices().values()] == [2.543]


def test_no_fee_leaves_the_sensor_price():
    eng = engine({"sell": True}, {"sensor.export": {"state": "2.633", "attributes": {}}}, "sensor.export")
    assert list(eng.sell_prices().values()) == [2.633]


def test_fee_off_the_fixed_price():
    assert engine({"sell": True, "sell_price": 0.5, "sell_fee": 0.09}).sell_fixed() == pytest.approx(0.41)
    assert engine({"sell": False, "sell_price": 0.5, "sell_fee": 0.09}).sell_fixed() == 0.0
    assert engine({"sell": True, "sell_price": 0.5, "sell_fee": None}).sell_fixed() == 0.5


def test_fee_off_the_tariff_plans_feed_in():
    eng = engine({"sell": True, "sell_fee": 0.05, "price_source": "tou",
                  "tou": {"default": 0.3, "periods": [], "sell_default": 0.0,
                          "sell_periods": [{"from": "18:00", "to": "21:00", "price": 0.15, "days": "all"}]}})
    vals = {t.hour: v for t, v in eng.sell_prices().items() if t.minute == 0}
    assert vals[19] == pytest.approx(0.10) and vals[12] == pytest.approx(-0.05)

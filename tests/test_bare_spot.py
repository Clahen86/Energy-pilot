"""A bare spot price (Home Assistant's own Nord Pool) outside Denmark gets the taxes, surcharge and VAT."""

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from energy_pilot.overview import Overview
from energy_pilot.pricefeed import collect, now_price

TZ = ZoneInfo("Europe/Amsterdam")


def fake(country, platform="nordpool", attrs=None, markup=0.15):
    ov = SimpleNamespace(
        ha=SimpleNamespace(config={"country": country}, states={"sensor.np": {"state": "0.10", "attributes": attrs or {}}}),
        controller=SimpleNamespace(_ent_reg={"sensor.np": {"platform": platform}}),
        settings={"markup": markup}, role=lambda r: "sensor.np" if r == "price" else None)
    ov.bare_spot = lambda: Overview.bare_spot(ov)
    return ov


def test_nord_pool_in_nl_gets_tax_and_vat():
    ov = fake("NL")
    add, vat = Overview.spot_extra(ov)
    assert (add, vat) == (0.15, 0.21)
    assert now_price(ov.ha.states, "sensor.np", TZ, 1.0, add, vat) == round(0.25 * 1.21, 5)


def test_left_alone_in_denmark_for_other_sensors_and_hacs_nord_pool():
    assert Overview.spot_extra(fake("DK")) == (0.0, 0.0)
    assert Overview.spot_extra(fake("NL", platform="frank_energie")) == (0.0, 0.0)
    assert Overview.spot_extra(fake("NL", attrs={"raw_today": []})) == (0.0, 0.0)


def test_collect_adds_to_every_slot():
    t = datetime(2026, 11, 26, 12, tzinfo=TZ).isoformat()
    prices, _ = collect({}, "sensor.np", [], TZ, [{"start": t, "price": 0.10}], 1.0, 0.15, 0.21)
    assert list(prices.values()) == [round(0.25 * 1.21, 5)]


def test_own_tariff_never_filled_in_keeps_the_chosen_price_sensor():
    states = {"input_number.buy": {"state": "0.3", "attributes": {}}}
    ov = SimpleNamespace(settings={"price_source": "tou", "roles": {"price": "input_number.buy"}},
                         ha=SimpleNamespace(states=states), detected={}, _phones=lambda: set())
    assert Overview.role(ov, "price") == "input_number.buy"
    ov.settings["tou"] = {"default": 0.3, "periods": []}
    assert Overview.role(ov, "price") is None  # a real own tariff wins

"""Prices from every kind of price integration, today and tomorrow, and filling what's missing."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from energy_pilot.pricefeed import collect, parse

TZ = ZoneInfo("Europe/Copenhagen")
DAY0 = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
T1 = DAY0 + timedelta(days=1)


def iso(d):
    return d.isoformat()


def test_stromligning_today_and_tomorrow_entity():
    states = {
        "sensor.stromligning_current_price_vat": {"attributes": {"unit_of_measurement": "kr/kWh", "prices": [
            {"start": iso(DAY0 + timedelta(hours=h)), "end": iso(DAY0 + timedelta(hours=h + 1)), "price": 2.0} for h in range(24)]}},
        "binary_sensor.stromligning_tomorrow_available_vat": {"attributes": {"prices": [
            {"start": iso(T1 + timedelta(hours=h)), "end": iso(T1 + timedelta(hours=h + 1)), "price": 1.5} for h in range(24)]}},
    }
    prices, info = collect(states, "sensor.stromligning_current_price_vat", [], TZ)
    assert prices[T1 + timedelta(hours=5)] == 1.5 and len(prices) == 48 and not info["tomorrow_missing"]


def test_nordpool_tibber_eds_shapes():
    nordpool = parse({"unit_of_measurement": "EUR/MWh", "raw_today": [{"start": DAY0, "end": DAY0 + timedelta(hours=1), "value": 100.0}],
                      "tomorrow": [50.0] * 24}, TZ, DAY0)
    assert nordpool[DAY0] == 0.1 and nordpool[T1 + timedelta(hours=3)] == 0.05
    tibber = parse({"today": [{"startsAt": iso(DAY0), "total": 0.31}]}, TZ, DAY0)
    assert tibber[DAY0] == 0.31
    eds = parse({"forecast": [{"hour": iso(T1), "price": 1.2}]}, TZ, DAY0)
    assert eds[T1] == 1.2


def test_missing_tomorrow_is_filled_at_the_users_level():
    states = {"sensor.my_price": {"attributes": {"prices": [{"start": iso(DAY0 + timedelta(hours=h)), "price": 3.0} for h in range(24)]}}}
    own = [{"start": iso(DAY0 + timedelta(hours=h)), "price": 2.5} for h in range(48)]  # own spot prices, 0.5 lower
    prices, info = collect(states, "sensor.my_price", own, TZ)
    assert prices[T1 + timedelta(hours=8)] == 3.0 and info["filled"] == 24


def test_octopus_rates_import_and_export_apart():
    base = "octopus_energy_electricity_19l1234_2100"
    t1 = DAY0 + timedelta(days=1)
    rate = lambda d, h, v: {"start": iso(d + timedelta(minutes=30 * h)), "end": iso(d + timedelta(minutes=30 * h + 30)), "value_inc_vat": v}
    states = {
        f"event.{base}_current_day_rates": {"state": "2026-11-08T00:00:00", "attributes": {"rates": [rate(DAY0, h, 0.20) for h in range(48)]}},
        f"event.{base}_next_day_rates": {"state": "x", "attributes": {"rates": [rate(t1, h, 0.10) for h in range(48)]}},
        f"event.{base}_export_current_day_rates": {"state": "x", "attributes": {"rates": [rate(DAY0, h, 0.15) for h in range(48)]}},
    }
    prices, info = collect(states, f"event.{base}_current_day_rates", [], TZ)
    assert prices[DAY0 + timedelta(minutes=30)] == 0.20 and prices[t1 + timedelta(hours=3)] == 0.10  # half hours, tomorrow too
    assert 0.15 not in prices.values()  # export kept apart
    from energy_pilot.pricefeed import now_price

    assert now_price(states, f"event.{base}_current_day_rates", TZ) == 0.20  # an event entity's state isn't a price


def test_stromligning_tomorrow_spot_price_is_not_mixed_in():
    """Bug: tomorrow's spot price alone (…_tomorrow_spotprice_vat) overwrote the full price."""
    full = [{"start": iso(T1 + timedelta(hours=h)), "price": 4.8 if h == 18 else 2.4} for h in range(24)]
    spot = [{"start": iso(T1 + timedelta(hours=h)), "price": 3.4 if h == 18 else 1.0} for h in range(24)]
    exvat = [{"start": iso(T1 + timedelta(hours=h)), "price": 3.9 if h == 18 else 1.9} for h in range(24)]
    states = {
        "sensor.stromligning_current_price_vat": {"attributes": {"prices": [{"start": iso(DAY0), "price": 2.0}]}},
        "binary_sensor.stromligning_tomorrow_available_vat": {"attributes": {"prices": full}},
        "binary_sensor.stromligning_tomorrow_spotprice_vat": {"attributes": {"prices": spot}},
        "binary_sensor.stromligning_tomorrow_available": {"attributes": {"prices": exvat}},  # without VAT
    }
    prices, _ = collect(states, "sensor.stromligning_current_price_vat", [], TZ)
    assert prices[T1 + timedelta(hours=18)] == 4.8


def test_amber_forecast_sensor_is_the_companion():
    from energy_pilot.pricefeed import companions

    states = {"sensor.amber_general_price": {"attributes": {}},
              "sensor.amber_general_forecast": {"attributes": {"forecasts": [{"start_time": iso(T1), "per_kwh": 0.3}]}},
              "sensor.amber_feed_in_forecast": {"attributes": {"forecasts": [{"start_time": iso(T1), "per_kwh": 0.1}]}}}
    assert companions(states, "sensor.amber_general_price") == ["sensor.amber_general_price", "sensor.amber_general_forecast"]


def test_edf_tempo_from_colours():
    """Tempo: a day runs 06-06, off-peak 22-06; tomorrow red -> tonight is still today's colour, tomorrow is dear."""
    from datetime import datetime

    from energy_pilot import tempo

    st = lambda v: {"state": v, "attributes": {}}
    states = {
        "sensor.tarif_actuel_tempo_6kva_ttc": st("0.1612"),
        "sensor.tarif_tempo_couleur_aujourd_hui": st("Bleu"),
        "sensor.tarif_tempo_couleur_demain": st("Rouge"),
        "sensor.tarif_tempo_couleur_hier": st("Blanc"),
        "sensor.tarif_bleu_tempo_heures_creuses_ttc": st("0.1325"),
        "sensor.tarif_bleu_tempo_heures_pleines_ttc": st("0.1612"),
        "sensor.tarif_blanc_tempo_heures_creuses_ttc": st("0.1499"),
        "sensor.tarif_blanc_tempo_heures_pleines_ttc": st("0.1871"),
        "sensor.tarif_rouge_tempo_heures_creuses_ttc": st("0.1575"),
        "sensor.tarif_rouge_tempo_heures_pleines_ttc": st("0.7060"),
    }
    now = datetime(2026, 11, 8, 13, tzinfo=TZ)
    p = tempo.prices(states, TZ, now)
    d = now.replace(hour=0)
    assert p[d + timedelta(hours=3)] == 0.1499  # 03:00 belongs to yesterday's (white) Tempo day
    assert p[d + timedelta(hours=14)] == 0.1612 and p[d + timedelta(hours=23)] == 0.1325  # today blue
    assert p[d + timedelta(days=1, hours=9)] == 0.7060  # tomorrow red, peak
    prices, _ = collect(states, "sensor.tarif_actuel_tempo_6kva_ttc", [], TZ)
    assert max(prices.values()) == 0.7060

"""Octopus Agile: the region comes from the tariff code, and Agile Predict's forecast is read in pounds."""

import asyncio
from types import SimpleNamespace

from energy_pilot.engine import Engine


class Resp:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def json(self, content_type=None):
        return [{"prices": [{"date_time": "2026-11-09T17:00:00Z", "agile_pred": 31.5},
                            {"date_time": "2026-11-09T17:30:00Z", "agile_pred": 28.5}]}]


def engine(states, settings=None):
    e = Engine.__new__(Engine)
    e.ha = SimpleNamespace(states=states, config={"time_zone": "Europe/London"}, session=SimpleNamespace(get=lambda *a, **k: Resp()))
    e.ov = SimpleNamespace(settings=settings or {}, role=lambda n: "sensor.octopus_rate" if n == "price" else None)
    e.agile_forecast = {}
    return e


def test_region_from_tariff_and_forecast_in_pounds():
    e = engine({"sensor.octopus_rate": {"state": "0.24", "attributes": {"tariff": "E-1R-AGILE-24-10-01-C"}}})
    assert e.agile_region() == "C"
    asyncio.run(e.refresh_agile_predict())
    assert sorted(round(v, 3) for v in e.agile_forecast.values()) == [0.285, 0.315]


def test_not_agile_no_forecast():
    e = engine({"sensor.octopus_rate": {"state": "0.24", "attributes": {"tariff": "E-1R-VAR-22-11-01-C"}}})
    assert e.agile_region() is None

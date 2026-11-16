import asyncio
from types import SimpleNamespace

from energy_pilot.replan import Replan


def _make():
    ha = SimpleNamespace(on_state=[], states={"sensor.price": {"state": "1"}})
    ov = SimpleNamespace(role=lambda r: "sensor.price" if r == "price" else None)
    return Replan(ha, ov)


def test_price_change_wakes_round():
    async def run():
        r = _make()
        r.SETTLE = 0.01
        r.refresh()
        assert "sensor.price" in r.watched
        r.on_state("sensor.other", {"state": "1"}, {"state": "2"})
        r.on_state("sensor.price", {"state": "1", "attributes": {"rates": [1]}}, {"state": "1", "attributes": {"rates": [1]}})
        assert not r._pending  # nothing changed
        r.on_state("sensor.price", {"state": "1", "attributes": {"rates": [1]}}, {"state": "1", "attributes": {"rates": [0.1]}})
        assert await r.sleep(2) is True

    asyncio.run(run())


def test_no_change_sleeps_full():
    async def run():
        r = _make()
        r.refresh()
        assert await r.sleep(0.05) is False

    asyncio.run(run())

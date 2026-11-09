"""Start: connect to Home Assistant, run the apps (shadow first), serve the panel."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from aiohttp import web

from .ha import HomeAssistant
from .cards import Cards
from .control import Controller
from .engine import Engine
from .overview import Overview
from .runner import Runner
from .web import make_app

DEFAULT_APPS = [
    {"name": "growatt_parallel", "module": "growatt_parallel", "class": "GrowattParallel"},
    {"name": "ev_charge_controller", "module": "ev_charge_controller", "class": "EvChargeController"},
    {"name": "husmodel", "module": "husmodel", "class": "HusModel"},
]


def seed(data_dir: Path, source: Path | None, patterns: list[str], shared: list[str]) -> None:
    """First start: copy the apps' own files (models, logs, state) from where they run now, so they continue
    with what they have learned. Folders other apps keep writing (e.g. heating data) are linked, read only."""
    import shutil

    marker = data_dir / ".energy_pilot_seeded"
    if source is None or not source.is_dir():
        return
    for name in shared:
        link = data_dir / name
        if not link.exists() and (source / name).exists():
            link.symlink_to(source / name)
    if marker.exists():
        return
    for pattern in patterns:
        for path in source.glob(pattern):
            dest = data_dir / path.name
            if dest.exists():
                continue
            if path.is_dir():
                shutil.copytree(path, dest)
            else:
                shutil.copy2(path, dest)
    marker.write_text("seeded from " + str(source))


def options() -> dict:
    try:
        return json.loads(Path("/data/options.json").read_text())
    except (OSError, ValueError):
        return {}


async def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    opts = options()
    apps_dir = Path(os.environ.get("APPS_DIR") or opts.get("apps_dir") or "/config/apps")
    data_dir = Path(os.environ.get("DATA_DIR") or opts.get("data_dir") or ("/config" if os.environ.get("SUPERVISOR_TOKEN") else "/data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    source = opts.get("seed_from") or os.environ.get("SEED_FROM")
    seed(data_dir, Path(source) if source else None,
         opts.get("seed_files") or ["growatt_*", "ev_session_state.json", "husmodel_state.json", "husmodel"],
         opts.get("shared") or ["indeklima_varme_data"])
    ha = HomeAssistant()
    # Your own AppDaemon apps run only when they are there (in Docker and for most homes: none - the engine plans).
    apps = [a for a in (opts.get("apps") or DEFAULT_APPS) if (apps_dir / f"{a['module']}.py").is_file()]
    runner = Runner(ha, apps_dir, data_dir, apps)
    asyncio.create_task(ha.run())
    overview = Overview(ha, data_dir)

    async def detect_hourly() -> None:
        while True:
            await ha.connected.wait()
            await overview.async_detect()
            await asyncio.sleep(3600)

    asyncio.create_task(detect_hourly())
    engine = Engine(ha, overview)
    overview.engine = engine
    controller = Controller(ha, overview, engine)
    overview.controller = controller

    async def run_engine() -> None:
        await ha.connected.wait()
        await asyncio.sleep(20)  # let the parts be found first
        learned = 0.0
        while True:
            try:
                if asyncio.get_running_loop().time() - learned > 86400 or not engine.profile:
                    await engine.learn()
                    learned = asyncio.get_running_loop().time()
                await engine.refresh_sources()
                await engine.refresh_service_prices()
                await engine.refresh_agile_predict()
                await engine.refresh_house_today()
                engine.run()
                await engine.review()
                if (not controller.entities["battery"] and not controller.entities["car"] or int(asyncio.get_running_loop().time()) % 3600 < 300
                        or any(p not in controller.entities for p in controller.car_parts())):  # a charger was just added
                    await controller.discover()
                await controller.tick()
            except Exception:  # noqa: BLE001 - tries again next round
                logging.getLogger("energy_pilot.engine").warning("Engine round failed", exc_info=True)
            await asyncio.sleep(300)

    asyncio.create_task(run_engine())

    async def run_car() -> None:
        """Every minute: the car's current follows the sun's surplus and the fuse (see carspeed.py)."""
        await ha.connected.wait()
        await asyncio.sleep(60)
        while True:
            try:
                if controller.entities["car"] or controller.platforms["car"] or controller.car_parts():
                    await controller.tick(("car",))  # charger 1 and the extra chargers (car2 …)
            except Exception:  # noqa: BLE001
                logging.getLogger("energy_pilot.car").debug("Car round failed", exc_info=True)
            await asyncio.sleep(60)

    asyncio.create_task(run_car())

    async def run_ledger() -> None:
        """Every half minute: what the battery holds and what it cost, and what it saved."""
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo as _Z

        from .pricefeed import collect

        await ha.connected.wait()
        await asyncio.sleep(30)
        while True:
            try:
                tz = _Z(ha.config.get("time_zone") or "UTC")
                now = _dt.now(tz)
                prices, _ = collect(ha.states, overview.role("price"), engine.own_prices or [], tz, engine.service_prices or [])
                past = [k for k in prices if k <= now]
                price = prices[max(past)] if past else None
                st, b = overview.settings, engine.settings()
                sell = float(st.get("sell_price") or 0) if st.get("sell") else 0.0
                sell = engine.sell_at(engine.sell_prices(), now, sell)  # a changing feed-in price, when chosen
                if (be := overview.role("battery_power")) and (bs := ha.states.get(be)):
                    try:
                        raw = float(bs.get("state")) * (1000 if str((bs.get("attributes") or {}).get("unit_of_measurement", "")).lower() == "kw" else 1)
                    except (TypeError, ValueError):
                        raw = None
                    engine.watch_sign(raw, overview.flow().get("soc"))
                f = overview.flow()
                engine.ledger.tick(now, f, price, sell, b.capacity_kwh, b.min_soc, b.efficiency,
                                   st.get("solar_value") or "free")
                engine.price_model.remember(prices, now)
                ev = overview.ev() or {}
                engine.habits.see(now, f.get("plug"), ev.get("session_kwh"))
                engine.batt_learn.see(f.get("battery"), f.get("soc"), 30 / 3600)
                engine.grid_peak.see(now, f.get("grid"))
                if now.minute % 10 == 0 and now.second < 30:
                    engine.learning.save()
            except Exception:  # noqa: BLE001
                logging.getLogger("energy_pilot.ledger").debug("Ledger round failed", exc_info=True)
            await asyncio.sleep(30)

    asyncio.create_task(run_ledger())
    asyncio.create_task(Cards(ha, overview, os.environ.get("BUILD_VERSION", "dev")).run())

    async def companion_setup() -> None:
        from . import companion

        await ha.connected.wait()
        companion.install()
        await companion.announce(ha.session)

    asyncio.create_task(companion_setup())
    web_runner = web.AppRunner(make_app(runner, overview))
    await web_runner.setup()
    await web.TCPSite(web_runner, "0.0.0.0", int(os.environ.get("PORT", 8099))).start()
    await runner.start()
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())

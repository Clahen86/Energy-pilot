"""Start: connect to Home Assistant, run the apps (shadow first), serve the panel."""

from __future__ import annotations

import asyncio
from datetime import datetime
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
         opts.get("seed_files") or ["growatt_*", "ev_session_state.json"],
         opts.get("shared") or [])
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
    from .curtail import Curtail

    curtail = Curtail(ha, overview, controller)  # stop selling solar when the price is negative
    from .replan import Replan

    replan = Replan(ha, overview)  # a new plan as soon as the prices change
    overview.curtail = curtail
    from .selftest import SelfTest

    overview.selftest = SelfTest(controller, overview)
    from .autofix import AutoFix

    overview.autofix = AutoFix(overview)
    from .telemetry import ErrorHandler, Telemetry
    from .web import REPORT_URL

    overview.telemetry = Telemetry(overview, REPORT_URL)
    logging.getLogger("energy_pilot").addHandler(ErrorHandler(overview.telemetry))

    async def run_telemetry() -> None:
        await ha.connected.wait()
        await asyncio.sleep(600)  # let it settle first: the plan, the parts, the ledger
        await overview.telemetry.run()

    asyncio.create_task(run_telemetry())

    async def run_recover() -> None:
        """A test cut short by a restart: its saved settings go back first."""
        await ha.connected.wait()
        await asyncio.sleep(15)
        try:
            await overview.selftest.recover()
        except Exception:  # noqa: BLE001
            logging.getLogger("energy_pilot.selftest").warning("Could not put the test's settings back", exc_info=True)

    asyncio.create_task(run_recover())

    from .timeline import Timeline, snapshot

    overview.timeline = Timeline(data_dir / "energy_pilot_timeline.jsonl")  # the last two days, sent with a report
    from .whatif import Hourly

    overview.hourly = Hourly(data_dir / "energy_pilot_hours.json")  # 30 days of hours, for "what if"
    from .tariffs import Tariffs

    overview.tariffs = Tariffs(data_dir)  # which electricity deal would have been cheapest

    async def run_engine() -> None:
        await ha.connected.wait()
        await asyncio.sleep(20)  # let the parts be found first
        learned = 0.0
        while True:
            try:
                own_changed = bool(overview.settings.get("own_history")) != engine.own_at_learn  # turned on: learn from it at once
                # Another meter chosen (or found): learn again at once - at most every 10 minutes, so a meter that
                # comes and goes can't have the 60 days of history asked for every round.
                meters_changed = engine.roles_at_learn is not None and engine.learn_roles() != engine.roles_at_learn \
                    and asyncio.get_running_loop().time() - learned > 600
                if asyncio.get_running_loop().time() - learned > 86400 or not engine.profile or own_changed or meters_changed:
                    await engine.learn()
                    learned = asyncio.get_running_loop().time()
                replan.refresh()
                await engine.refresh_sources()
                await engine.refresh_service_prices()
                await engine.refresh_agile_predict()
                await engine.refresh_house_today()
                await engine.refresh_retro()  # "what you would have saved" for a new install (once, then every 3 days)
                # The controls first: the plan asks them whether the battery can sell - planned before they were
                # found (the first round after a start), it planned without selling and said selling was blocked.
                if (not controller.discovered or not controller.entities["battery"] and not controller.entities["car"] or int(asyncio.get_running_loop().time()) % 3600 < 300
                        or any(p not in controller.entities for p in controller.car_parts() + controller.bat_parts())):  # a charger or battery was just added
                    await controller.discover()
                engine.run()
                await engine.review()
                await controller.tick()
                await curtail.tick()
                overview.timeline.add(snapshot(overview, engine, controller))
                fl, ns = overview.flow() or {}, getattr(engine, "now_slot", None) or {}
                overview.hourly.add(datetime.now(engine.tz), fl.get("house"), fl.get("sun", fl.get("pv")), ns.get("price"), ns.get("sell"))
                await engine.refresh_whatif()
                await engine.join_power_down()
                await engine.refresh_tariffs()
            except Exception:  # noqa: BLE001 - tries again next round
                logging.getLogger("energy_pilot.engine").warning("Engine round failed", exc_info=True)
            # Every 5 minutes, and just after each quarter hour starts - prices change on the quarter, so the battery
            # follows the plan from the first minute of a slot instead of up to 5 minutes late.
            import time as _time

            to_quarter = 900 - _time.time() % 900 + 5
            if await replan.sleep(min(300, to_quarter)):
                logging.getLogger("energy_pilot.engine").info("Prices changed - making a new plan")

    asyncio.create_task(run_engine())

    async def run_car() -> None:
        """Every minute: the car's current follows the sun's surplus and the fuse (see carspeed.py)."""
        await ha.connected.wait()
        await asyncio.sleep(60)
        while True:
            try:
                await overview.async_plug_marks()  # what the meter showed at plug-in (charged this session)
                if controller.entities["car"] or controller.platforms["car"] or controller.car_parts():
                    await controller.tick(("car",))  # charger 1 and the extra chargers (car2 …)
            except Exception:  # noqa: BLE001
                logging.getLogger("energy_pilot.car").debug("Car round failed", exc_info=True)
            await asyncio.sleep(60)

    asyncio.create_task(run_car())

    from .nightupdate import NightUpdate

    night_update = NightUpdate(overview, ha)

    async def run_keep() -> None:
        """Every minute: inverters that forget their settings (Victron) get them again on time (see Controller.keep)."""
        await ha.connected.wait()
        await asyncio.sleep(90)
        while True:
            try:
                # A grid charge under an import limit: looked at every minute, so it gives way soon when the house
                # suddenly takes more (the oven, the kettle) - the plan's own round can be five minutes.
                last = (controller.last.get("battery") or {}) if hasattr(controller, "last") else {}
                if last.get("intent") == "charge" and controller.mode("battery") == "control" and (engine.settings().import_limit_kw or overview.settings.get("fuse_a")):
                    await controller.tick(("battery", *controller.bat_parts()))
            except Exception:  # noqa: BLE001
                logging.getLogger("energy_pilot.engine").debug("Charge limit check failed", exc_info=True)
            for job in (controller.keep, controller.guard, controller.recheck):
                try:
                    await job()
                except Exception:  # noqa: BLE001
                    logging.getLogger("energy_pilot.engine").debug("Minute check failed", exc_info=True)
            try:
                overview.autofix.run()
            except Exception:  # noqa: BLE001
                logging.getLogger("energy_pilot.autofix").debug("Autofix failed", exc_info=True)
            try:
                from . import trial as _trial

                await _trial.tick(overview, datetime.now(__import__("zoneinfo").ZoneInfo(ha.config.get("time_zone") or "UTC")))  # 24 h over: shadow again
            except Exception:  # noqa: BLE001
                logging.getLogger("energy_pilot.trial").debug("Trial check failed", exc_info=True)
            try:
                await night_update.tick(datetime.now(__import__("zoneinfo").ZoneInfo(ha.config.get("time_zone") or "UTC")))  # a waiting version, at night
            except Exception:  # noqa: BLE001
                logging.getLogger("energy_pilot.nightupdate").debug("Night update check failed", exc_info=True)
            await asyncio.sleep(60)

    asyncio.create_task(run_keep())

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
                if getattr(overview, "selftest", None):
                    try:
                        overview.selftest.night_check(now)  # only if the user said yes to testing by itself
                    except Exception:  # noqa: BLE001
                        logging.getLogger("energy_pilot.selftest").debug("Night check failed", exc_info=True)
                prices, _ = collect(ha.states, overview.role("price"), engine.own_prices or [], tz, engine.service_prices or [], overview.price_scale(),
                                     *overview.spot_extra())
                past = [k for k in prices if k <= now]
                price = prices[max(past)] if past else None
                st, b = overview.settings, engine.settings()
                sell = engine.sell_at(engine.sell_prices(), now, engine.sell_fixed())  # a changing feed-in price, when chosen
                if (be := overview.role("battery_power")) and (bs := ha.states.get(be)) and not overview.battery_pair():
                    try:
                        raw = float(bs.get("state")) * (1000 if str((bs.get("attributes") or {}).get("unit_of_measurement", "")).lower() == "kw" else 1)
                    except (TypeError, ValueError):
                        raw = None
                    engine.watch_sign(raw, overview.flow().get("soc"))
                f = overview.flow()
                engine.ledger.tick(now, f, price, sell, b.capacity_kwh, b.min_soc, b.efficiency,
                                   st.get("solar_value") or "free", b.max_charge_kw, b.max_discharge_kw)
                engine.battstats.tick(now, f, b.min_soc)
                engine.price_model.remember(prices, now)
                ev = overview.ev() or {}
                engine.habits.see(now, f.get("plug"), ev.get("session_kwh"))
                # each charger's real charge, measured beside the one Energy Pilot would make (for chargers in shadow)
                extra = f.get("cars") or []
                # more cars than chargers: which car is in each charger now (carlist.py)
                from . import carlist

                plugged = {"car": bool(f.get("plug")), **{f"car{i + 2}": bool(c.get("plug")) for i, c in enumerate(extra)}}
                watch = getattr(engine, "car_watch", None) or carlist.PowerWatch()
                engine.car_watch = watch
                own = None if f.get("ev") is None else f["ev"] - sum((c.get("power") or 0.0) for c in extra)
                done = watch.see(plugged, {"car": own, **{f"car{i + 2}": c.get("power") for i, c in enumerate(extra)}})
                if done and carlist.cars(st) and (learned := carlist.learn(st, done)):
                    overview.save(learned)  # what each car takes, from charges where it was sure which car it was
                if moved := carlist.assign(st, ha.states, plugged, {p: watch.now_kw(p) for p in plugged}):
                    overview.save(moved)
                    engine.run()  # another car: its level, target and ready time - a new plan now
                own_w = None if f.get("ev") is None else f["ev"] - sum((c.get("power") or 0.0) for c in extra)
                engine.ghosts.see("car", now, f.get("plug"), own_w, price, 30,
                                  engine.ghosts.sun_to_car(own_w, f.get("pv"), f.get("grid"), f.get("battery")), sell)
                for i, c in enumerate(extra):
                    engine.ghosts.see(f"car{i + 2}", now, c.get("plug"), c.get("power"), price, 30)
                car1 = carlist.car_in(st, "car")
                if car1 is None:  # with more cars on one charger the size is each car's own, not learned as one
                    engine.car_size.see(f.get("plug"), ev.get("soc"), ev.get("session_kwh"), own_w)
                from .evsoc import trip_done

                if trip_done({"ev_trip": car1.get("trip")} if car1 else st, f.get("plug"), getattr(engine, "_was_plugged", False), ev.get("soc")):
                    # the car left full: back to the everyday target
                    overview.save(carlist.update_car(st, car1["id"], {"trip": False}) if car1 else {"ev_trip": False})
                engine._was_plugged = bool(f.get("plug"))
                # an extra car's trip button the same: off when it leaves full
                was = getattr(engine, "_was_plugged_extra", {})
                conf = list(st.get("chargers") or [])
                from .chargers import extras as _extras

                for i, (c, x) in enumerate(zip(_extras(st), extra)):
                    car = carlist.car_in(st, f"car{i + 2}")
                    if (car or c).get("trip") and was.get(i) and not x.get("plug") and (x.get("soc") is None or x["soc"] >= 95):
                        if car:
                            overview.save(carlist.update_car(st, car["id"], {"trip": False}))
                        else:
                            conf[conf.index(c)] = {**c, "trip": False}
                            overview.save({"chargers": conf})
                engine._was_plugged_extra = {i: bool(x.get("plug")) for i, x in enumerate(extra)}
                engine.batt_learn.see(f.get("battery"), f.get("soc"), 30 / 3600)
                engine.ac_steps.see(__import__("time").time(), f)
                engine.batt_learn.see_temp(f.get("battery"), f.get("soc"), engine.battery_temp())
                engine.grid_peak.see(now, f.get("grid"))
                engine.export_cap.see(now, f.get("grid"))
                engine.house_hist.see(now, f.get("house"))  # the house's own history (used when HA keeps no statistics)
                if st.get("things"):
                    # in shadow nothing is switched: the things act only when Energy Pilot controls something
                    engine.things.registry = getattr(controller, "registry", None) or []  # a water heater's own temperature
                    await engine.things.tick(ha, st, now, price, sell, f.get("grid"), act=any(controller.mode(p) == "control" for p in controller.parts()))
                    if engine.things.replan:  # a machine was just paused: its start time now
                        engine.things.replan = False
                        engine.run()
                if getattr(overview, "selftest", None):
                    await overview.selftest.retry_pending()  # settings a test left while their device was offline
                bp = controller.last.get("battery") if hasattr(controller, "last") else None
                engine.follow.see(now, controller.mode("battery"), bp, f,
                                  ha.states, controller.entities.get("battery") or [])
                from .powertariff import counts as _pt_counts, kind as _pt_kind

                engine.month_peak.see(now, f.get("grid"), _pt_kind(st, ha.config.get("country"))[0], _pt_counts(st, now))
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
    from .web import panel_password

    web_runner = web.AppRunner(make_app(runner, overview, panel_password(data_dir)))
    await web_runner.setup()
    await web.TCPSite(web_runner, "0.0.0.0", int(os.environ.get("PORT", 8099))).start()
    await runner.start()
    # Stopped by the Supervisor (SIGTERM): let go of the battery first, so nothing is left standing while away.
    import signal

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
    await stop.wait()
    if overview.controller:
        try:
            await overview.controller.let_go()
        except Exception:  # noqa: BLE001
            logging.getLogger("energy_pilot").warning("Stopping: could not let go of the battery", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())

"""Start: connect to Home Assistant, run the apps (shadow first), serve the panel."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from aiohttp import web

from .ha import HomeAssistant
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
    data_dir = Path(os.environ.get("DATA_DIR") or opts.get("data_dir") or "/config")
    data_dir.mkdir(parents=True, exist_ok=True)
    source = opts.get("seed_from") or os.environ.get("SEED_FROM")
    seed(data_dir, Path(source) if source else None,
         opts.get("seed_files") or ["growatt_*", "ev_session_state.json", "husmodel_state.json", "husmodel"],
         opts.get("shared") or ["indeklima_varme_data"])
    ha = HomeAssistant()
    runner = Runner(ha, apps_dir, data_dir, opts.get("apps") or DEFAULT_APPS)
    asyncio.create_task(ha.run())
    web_runner = web.AppRunner(make_app(runner))
    await web_runner.setup()
    await web.TCPSite(web_runner, "0.0.0.0", int(os.environ.get("PORT", 8099))).start()
    await runner.start()
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())

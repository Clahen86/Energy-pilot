"""The companion integration: put into Home Assistant's custom_components by the app, and announced to Home Assistant
(Supervisor discovery), so after one restart "Energipilot found" shows under Devices & services - with buttons and
sensors for the car, the battery minimum, the style and "everything back to shadow"."""

from __future__ import annotations

import filecmp
import logging
import os
from pathlib import Path
import shutil
import socket

_LOGGER = logging.getLogger(__name__)
SOURCE = Path(__file__).parent.parent / "integration" / "energy_pilot"
TARGET = Path("/homeassistant/custom_components/energy_pilot")


def _same(a: Path, b: Path) -> bool:
    if not b.is_dir():
        return False
    cmp = filecmp.dircmp(a, b)
    return not (cmp.left_only or cmp.diff_files) and all(_same(a / d, b / d) for d in cmp.common_dirs if d != "__pycache__")


def install() -> bool:
    """Copy the integration in when it's missing or older. Returns True when Home Assistant must restart to load it."""
    if not SOURCE.is_dir() or not TARGET.parent.parent.is_dir():
        return False
    if _same(SOURCE, TARGET):
        return False
    new = not TARGET.exists()
    try:
        TARGET.parent.mkdir(exist_ok=True)
        if TARGET.exists():
            shutil.rmtree(TARGET)
        shutil.copytree(SOURCE, TARGET, ignore=shutil.ignore_patterns("__pycache__"))
    except OSError:
        _LOGGER.warning("Could not install the companion integration", exc_info=True)
        return False
    _LOGGER.info("Companion integration %s - restart Home Assistant to load it", "installed" if new else "updated")
    return True


async def announce(session) -> None:
    """Tell Home Assistant where the app's API is (shows up as discovered after a restart)."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return
    try:
        async with session.post("http://supervisor/discovery", headers={"Authorization": f"Bearer {token}"},
                                json={"service": "energy_pilot", "config": {"host": socket.gethostname(), "port": int(os.environ.get("PORT", 8099))}}) as r:
            if r.status >= 400:
                _LOGGER.info("Discovery not accepted (%s)", r.status)
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Discovery failed", exc_info=True)

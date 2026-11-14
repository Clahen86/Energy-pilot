"""Can this machine run the learning models? Checked once.

numpy 2 needs a CPU with x86-64-v2 (SSE4.2, POPCNT). An old CPU - or a Proxmox VM with the CPU type "kvm64" - stops
it with a RuntimeError when it loads. Then the simple forecasts are used, without an error every hour.
"""

from __future__ import annotations

import logging

_LOGGER = logging.getLogger(__name__)
_state: dict[str, str | bool | None] = {}


def ok() -> bool:
    if "ok" not in _state:
        try:
            from sklearn.ensemble import GradientBoostingRegressor, HistGradientBoostingRegressor  # noqa: F401

            _state.update(ok=True, why=None, detail=None)
        except Exception as err:  # noqa: BLE001 - ImportError, or RuntimeError from numpy on an old CPU
            text = str(err)
            cpu = any(k in text.lower() for k in ("baseline", "x86_v", "cpu", "illegal instruction", "sse", "avx"))
            _state.update(ok=False, why="cpu" if cpu else "missing" if isinstance(err, ImportError) else type(err).__name__, detail=text[:300])
            _LOGGER.info("Learning models off (%s): %s", _state["why"], text[:300])
    return bool(_state["ok"])


def why() -> str | None:
    ok()
    return _state.get("why")  # type: ignore[return-value]


def info() -> dict[str, object]:
    ok()
    return {"ok": _state.get("ok"), "why": _state.get("why"), "detail": _state.get("detail")}

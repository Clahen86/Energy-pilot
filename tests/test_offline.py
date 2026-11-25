"""Without internet the plan runs on, and the user is told - and told when control has to wait for the cloud."""
import time
from types import SimpleNamespace

from energy_pilot.engine import Engine


def test_offline_timer():
    e = SimpleNamespace()
    Engine.net_failed(e)
    t0 = e.net_down_since
    Engine.net_failed(e)
    assert e.net_down_since == t0  # the first failure counts
    assert Engine.offline_for(e) is not None
    Engine.net_ok(e)
    assert Engine.offline_for(e) is None

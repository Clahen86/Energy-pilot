"""Octopus Power Down sessions: joined by itself, and the reward planned for."""

import asyncio
from datetime import datetime, timedelta, timezone

from energy_pilot.engine import Hour
from energy_pilot.powerdown import apply, join

NOW = datetime(2026, 12, 1, 12, tzinfo=timezone.utc)
E = "event.octopus_energy_a_123_octoplus_power_down_events"


def _states(available=(), joined=()):
    return {E: {"state": "x", "attributes": {"available_events": list(available), "joined_events": list(joined)}}}


class FakeHA:
    def __init__(self):
        self.calls = []

    async def call_service(self, domain, service, data, response=False):
        self.calls.append((domain, service, dict(data)))


def test_joins_sessions_on_offer_once_and_never_past_ones():
    ev = {"code": "A1", "start": (NOW + timedelta(hours=5)).isoformat(), "end": (NOW + timedelta(hours=6)).isoformat()}
    old = {"code": "Z9", "start": (NOW - timedelta(hours=1)).isoformat()}
    ha, done = FakeHA(), set()
    assert asyncio.run(join(ha, _states([ev, old]), NOW, done)) == ["A1"]
    assert ha.calls == [("octopus_energy", "join_octoplus_power_down_session_event", {"entity_id": E, "event_code": "A1"})]
    assert asyncio.run(join(ha, _states([ev]), NOW, done)) == []  # not twice


def test_reward_added_to_the_session_slots():
    joined = {"start": (NOW + timedelta(hours=2)).isoformat(), "end": (NOW + timedelta(hours=3)).isoformat(), "octopoints_per_kwh": 1600}
    hours = [Hour(NOW + timedelta(minutes=30 * i), 0.25, 0.15, 0.3, 0.0, 0.5) for i in range(8)]
    used = apply(hours, NOW, _states(joined=[joined]))
    assert len(used) == 1
    assert [round(h.price, 2) for h in hours] == [0.25] * 4 + [2.25, 2.25] + [0.25] * 2  # 1600 points = £2 per kWh
    assert round(hours[4].sell, 2) == 2.15
    assert apply(hours, NOW + timedelta(hours=4), _states(joined=[joined])) == []  # over

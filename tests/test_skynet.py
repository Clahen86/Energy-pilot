"""The sky network (skynet.py): cells, clouds upwind, grid failures nearby."""
from datetime import datetime, timedelta, timezone

from energy_pilot import skynet

HOME = (55.64, 12.08)  # Roskilde
NOW = datetime(2026, 11, 20, 11, 0, tzinfo=timezone.utc)


class W:
    def __init__(self, wind_dir, wind):
        self.w = {"wind_dir": wind_dir, "wind": wind}

    def at(self, _when):
        return self.w


def _west(km, ratio, n=3):
    """A cell `km` west of home."""
    import math
    return {"cell": "x", "lat": HOME[0], "lon": HOME[1] - km / (111.2 * math.cos(math.radians(HOME[0]))), "n": n, "ratio": ratio}


def test_cell_hides_the_position():
    assert skynet.cell(55.6417, 12.0803) == "55.6|12.00"
    assert skynet.cell(55.6417, 12.0803) == skynet.cell(55.69, 12.14)
    lat, lon = skynet.middle("55.6|12.00")
    assert abs(lat - 55.65) < 1e-9 and abs(lon - 12.075) < 1e-9


def test_clouds_from_the_west_reach_the_next_hour():
    times = [NOW + timedelta(hours=i) for i in range(4)]
    sun = [2.0, 2.0, 2.0, 2.0]
    near = [_west(50, 0.3)]  # 50 km west, wind from the west at 40 km/h: here in 1¼ hours
    out = skynet.adjust(near, HOME, times, sun, NOW, W(270, 40))
    assert out[0] == 2.0  # this half hour: not yet
    assert out[1] < 1.5  # the hour it arrives: pulled down
    assert out[3] == 2.0  # too far out


def test_clouds_downwind_or_no_wind_change_nothing():
    times = [NOW + timedelta(hours=i) for i in range(3)]
    sun = [2.0, 2.0, 2.0]
    assert skynet.adjust([_west(40, 0.3)], HOME, times, sun, NOW, W(90, 40)) == sun  # wind from the east
    assert skynet.adjust([_west(40, 0.3)], HOME, times, sun, NOW, W(270, 2)) == sun  # calm
    assert skynet.adjust([_west(40, 0.3, n=1)], HOME, times, sun, NOW, W(270, 40)) == sun  # a single house


def test_outage_nearby():
    near = [{"lat": HOME[0] + 0.1, "lon": HOME[1], "down": 3, "reporting": 4}]
    out = skynet.outage_near(near, HOME)
    assert out == {"houses": 3, "km": 11}
    st = skynet.storm(out, NOW)
    assert st["kind"] == "outage" and st["from"] == NOW.isoformat()


def test_no_outage_when_few_or_far():
    assert skynet.outage_near([{"lat": HOME[0] + 0.1, "lon": HOME[1], "down": 1, "reporting": 1}], HOME) is None
    assert skynet.outage_near([{"lat": HOME[0] + 0.1, "lon": HOME[1], "down": 2, "reporting": 10}], HOME) is None
    assert skynet.outage_near([{"lat": HOME[0] + 1.0, "lon": HOME[1], "down": 5, "reporting": 5}], HOME) is None


def test_grid_voltage():
    states = {"sensor.inv_grid_voltage": {"state": "231", "attributes": {"unit_of_measurement": "V"}}}
    e = skynet.grid_voltage_entity(states)
    assert e == "sensor.inv_grid_voltage"
    assert skynet.grid_down(states, e) is False
    states[e]["state"] = "0"
    assert skynet.grid_down(states, e) is True
    assert skynet.grid_down(states, None) is None

"""Shared knowledge (common.py): a new installation leans on what others learned, then lets go."""
from types import SimpleNamespace

from energy_pilot import common
from energy_pilot.learning import Learning


def _ov(common_data, country="DK", sun_source="sensor"):
    return SimpleNamespace(settings={"community": {"common": common_data}}, sun_source=sun_source,
                           ha=SimpleNamespace(config={"country": country}))


SHARED = {"sun": {"DK|sensor": {"cloudy": 0.8, "clear": 0.9, "n": 4}}, "eff": {"growatt|lfp": {"eff": 0.87, "n": 3}}}


def test_sun_bias_for_own_country_and_source():
    assert common.sun_bias(_ov(SHARED)) == {"cloudy": 0.8, "clear": 0.9, "n": 4}
    assert common.sun_bias(_ov(SHARED, country="GB")) is None
    assert common.sun_bias(_ov(SHARED, sun_source="own")) is None
    assert common.sun_bias(_ov({})) is None


def test_sun_bias_out_of_range_is_ignored():
    assert common.sun_bias(_ov({"sun": {"DK|sensor": {"cloudy": 5, "clear": 0.9}}})) is None


def test_efficiency_by_profile_and_type():
    assert common.efficiency(_ov(SHARED), "growatt", "lfp") == 0.87
    assert common.efficiency(_ov(SHARED), "deye", "lfp") is None
    assert common.efficiency(_ov(SHARED), None, "lfp") is None
    assert common.efficiency(_ov({"eff": {"growatt|lfp": {"eff": 0.5}}}), "growatt", "lfp") is None


def test_blend_fades_to_own():
    assert common.blend(1.0, 0.8, 0) == 0.8
    assert abs(common.blend(1.0, 0.8, 7) - 0.9) < 1e-9
    assert common.blend(1.0, 0.8, 14) == 1.0
    assert common.blend(1.0, None, 0) == 1.0


def test_learning_sun_uses_shared_while_young(tmp_path):
    lr = Learning(tmp_path)
    assert lr.sun(10, 80) == 10  # nothing shared: own bias (1.0)
    lr.shared_sun = lambda: {"cloudy": 0.8, "clear": 0.9}
    assert abs(lr.sun(10, 80) - 8) < 1e-9  # day 0: the shared cloudy bias
    assert abs(lr.sun(10, 10) - 9) < 1e-9  # clear
    lr.state["reports"] = [{}] * 14
    assert lr.sun(10, 80) == 10  # two weeks of its own: its own bias only


def test_taper_by_profile_and_model():
    ov = _ov({"taper": {"growatt|ARK": {"taper": [[98, 0.3], [95, 0.52]], "n": 3}}})
    assert common.taper(ov, "growatt", "ARK") == ((95.0, 0.52), (98.0, 0.3))
    assert common.taper(ov, "growatt", "other") == ()
    assert common.taper(ov, None, "ARK") == ()
    assert common.taper(_ov({"taper": {"growatt|ARK": {"taper": [["x", 1]]}}}), "growatt", "ARK") == ()


def test_peer_key_matches_the_worker():
    assert common.peer_key("DK", 11.5, True) == "DK|10|car"
    assert common.peer_key("DK", 12.5, False) == "DK|15|nocar"  # rounds half up, like JavaScript
    assert common.peer_key("DK", None, True) is None


def test_peers_and_health_in_info():
    shared = {"peers": {"DK|10|car": {"saved": 210, "n": 5, "features": {"export": {"on": 260, "off": 190, "n": 5}}}},
              "health": {"ARK": {"ratio": 0.9, "n": 4}}}
    info = common.info(_ov(shared), 3, 11.5, True, "ARK", 10.8, 12.8)
    assert info["peers"]["saved"] == 210
    assert info["health"] == {"mine": 0.84, "others": {"ratio": 0.9, "n": 4}}
    assert common.info(_ov({}), 3)["peers"] is None


def test_tariff_from_neighbours_in_the_same_cell():
    home = (55.64, 12.08)
    ov = _ov({"tariff": {"55.6|12.00": {"low": 0.12, "high": 0.35, "peak": 1.04, "n": 3}}})
    assert common.tariff(ov, home) == {"low": 0.12, "high": 0.35, "peak": 1.04}
    assert common.tariff(ov, (56.2, 10.2)) is None
    assert common.tariff(ov, None) is None

"""The shared house model: plain-JSON trees walked like scikit-learn, checked before use, a third way in the blend."""

import hashlib
import json
from datetime import datetime, timedelta

from energy_pilot import sharedmodel
from energy_pilot.blend import MIN_DAYS, Mixer

# one stump on "prev" (feature 6): <= 1.0 -> +0.1, else +0.5; missing goes left
TREE = {"f": [6, 0, 0], "t": [1.0, 0, 0], "l": [1, 0, 0], "r": [2, 0, 0], "m": [1, 0, 0], "leaf": [0, 1, 1], "v": [0, 0.1, 0.5]}


def _model(**kw):
    m = {"schema": 1, "kind": "house", "features": sharedmodel.FEATURES, "countries": ["DK", "SE"], "base": 0.4,
         "trees": [TREE], "clip": 1.5}
    m["probe"] = [[[0, 0, 1, 0, 0, 0, 0.5, 0.5], 0.5], [[0, 0, 1, 0, 0, 0, 2.0, 2.0], 0.9]]
    m.update(kw)
    return m


def test_trees_are_walked_like_scikit_learn():
    m = _model()
    assert sharedmodel.predict(m, [0, 0, 1, 0, 0, 0, 0.5, 0]) == 0.5
    assert sharedmodel.predict(m, [0, 0, 1, 0, 0, 0, 3.0, 0]) == 0.9
    assert sharedmodel.predict(m, [0, 0, 1, 0, 0, 0, None, 0]) == 0.5  # missing: left


def test_only_what_the_worker_named_and_what_gives_its_own_answers():
    body = json.dumps(_model()).encode()
    assert sharedmodel.check(body, hashlib.sha256(body).hexdigest())
    assert sharedmodel.check(body, "0" * 64) is None  # not the one named
    bad = json.dumps(_model(probe=[[[0, 0, 1, 0, 0, 0, 0.5, 0.5], 9.9]])).encode()
    assert sharedmodel.check(bad, None) is None  # its own answers don't match
    assert sharedmodel.check(json.dumps(_model(features=["x"])).encode(), None) is None


def test_house_hours_from_the_homes_own_level():
    now = datetime(2026, 11, 23, 12)
    real = {now - timedelta(hours=i): 0.8 for i in range(1, 24 * 8)}
    times = [now + timedelta(hours=i) for i in range(3)]
    out = sharedmodel.house(_model(), real, times, "DK", 10, False)
    assert out == [0.5, 0.5, 0.5]
    assert sharedmodel.house(_model(), real, times, "US", 10, False) == [None] * 3  # not trained on that country
    assert sharedmodel.house(None, real, times, "DK", 10, False) == [None] * 3


def test_the_shared_way_earns_its_share_and_the_old_blend_is_unchanged():
    old, new = Mixer({}), Mixer({})
    for _ in range(MIN_DAYS["house"] + 5):
        old.update("house", 0.4, 0.3, 60)
        new.update("house", 0.4, 0.3, 60)
    assert old.share("house") == new.share("house") and old.common_share("house") == 0.0
    m = Mixer({})
    for i in range(MIN_DAYS["house"] + 10):
        m.update("house", 0.4, 0.4, 60, 0.2)
        if i < MIN_DAYS["house"] - 1:
            assert m.common_share("house") == 0.0  # no say for the first three weeks
    assert m.common_share("house") > m.share("house")
    assert Mixer.mix3(1.0, 2.0, None, 0.5, 0.3) == 1.5  # no shared number: as the two-way mix
    assert Mixer.mix3(1.0, 1.0, 2.0, 0.2, 0.5) == 1.5

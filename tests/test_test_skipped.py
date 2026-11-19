"""A skipped self-test is offered again after two weeks; one skipped before that came stays skipped."""

from energy_pilot.web import ASK_AGAIN_S
from energy_pilot.web import test_skipped as skipped


def test_skipped_comes_back_after_two_weeks():
    assert skipped(None) is False and skipped(True) is True
    assert skipped(1000, now=1000 + 3600) is True
    assert skipped(1000, now=1000 + ASK_AGAIN_S + 1) is False

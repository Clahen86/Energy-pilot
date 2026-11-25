"""An Easee with the owner's own start/stop switch: Easee's current and pause/resume stay, and the switch is used too
(an Easee waiting for a start isn't started by "resume")."""

from energy_pilot import adapters


def test_easee_with_own_switch():
    calls = adapters.charger_calls("charge", ["switch.skur_easee_startstop"], "easee", 10, "dev1", {},
                                   chosen="switch.skur_easee_startstop")
    services = [(c["domain"], c["service"]) for c in calls]
    assert ("easee", "set_charger_dynamic_limit") in services and ("easee", "action_command") in services
    assert ("switch", "turn_on") in services and calls[-1]["data"]["entity_id"] == "switch.skur_easee_startstop"
    stop = adapters.charger_calls("stop", [], "easee", 6, "dev1", {}, chosen="switch.skur_easee_startstop")
    assert stop[-1]["service"] == "turn_off"


def test_easee_without_own_switch_unchanged():
    calls = adapters.charger_calls("charge", [], "easee", 10, "dev1", {})
    assert all(c["domain"] == "easee" for c in calls)


def test_a_pause_switch_is_turned_the_other_way():
    calls = adapters.charger_calls("charge", [], "easee", 10, "dev1", {}, chosen="switch.easee_pause")
    assert calls[-1]["service"] == "turn_off"

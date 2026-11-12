"""Who changed a setting, and when: a minimum that "moves by itself" shows its source in the diagnosis."""

import json

from energy_pilot.overview import Overview


class HA:
    def __init__(self):
        self.states, self.config = {}, {"time_zone": "Europe/Copenhagen"}


def test_changes_are_logged_with_source(tmp_path):
    (tmp_path / "energy_pilot_settings.json").write_text(json.dumps({"roles": {}, "battery_min_soc": 15}))
    o = Overview(HA(), tmp_path)
    o.save({"battery_min_soc": 10}, "home_assistant")
    o.save({"battery_min_soc": 10}, "app")  # no change: not logged
    o.save({"battery_targets": [{"time": "07:00", "soc": 80}]}, "app")  # lists are not logged
    log = o.settings["change_log"]
    assert [(x["key"], x["from"], x["to"], x["by"]) for x in log] == [("battery_min_soc", 15, 10, "home_assistant")]
    assert o.settings["battery_min_soc"] == 10


def test_log_keeps_the_last_40(tmp_path):
    o = Overview(HA(), tmp_path)
    for i in range(50):
        o.save({"battery_min_soc": i}, "app")
    assert len(o.settings["change_log"]) == 40 and o.settings["change_log"][-1]["to"] == 49

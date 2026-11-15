from energy_pilot.setupinfo import mask

WORDS = [("work", "<zone>"), ("sommerhus", "<zone>"), ("home", "<home>"), ("lilly", "<person>")]


def test_zone_words_that_are_the_integrations_own_stay():
    assert mask("select.foxess_work_mode", {}, {}, WORDS) == "select.foxess_work_mode"
    assert mask("sensor.evcc_home_power", {}, {}, WORDS) == "sensor.evcc_home_power"


def test_real_personal_words_still_masked():
    assert mask("sensor.sommerhus_temperature", {}, {}, WORDS) == "sensor.<zone>_temperature"
    assert mask("sensor.lilly_phone_battery", {}, {}, WORDS) == "sensor.<person>_phone_battery"

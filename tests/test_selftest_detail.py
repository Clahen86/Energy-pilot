"""A failed self-test step says why, without names - so a fault can be mended from the data, not guessed."""

from energy_pilot.selftest import error_kind


def test_error_kinds():
    assert error_kind("switch.turn_on: Rate limit exceeded for car ABC123") == "switch.turn_on:rate_limit"
    assert error_kind("switch.turn_on: Vehicle is not plugged in") == "switch.turn_on:car_not_ready"
    assert error_kind("select.select_option: Option Force Charge is not valid for entity select.my_house_mode") == "select.select_option:bad_option"
    assert error_kind("number.set_value: Value 6000 for number.x is outside valid range 0 - 5000") == "number.set_value:bad_value"
    assert error_kind("huawei_solar.forcible_charge_soc: Something odd") == "huawei_solar.forcible_charge_soc:other"
    assert error_kind("weird text") == "?:other"


def test_names_never_go_out():
    k = error_kind("switch.turn_on: Clauss Tesla in Garage refused: unauthorized")
    assert "Tesla" not in k and "Garage" not in k and k.endswith(":auth")

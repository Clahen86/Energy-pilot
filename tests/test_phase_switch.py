from energy_pilot.adapters import phase_control
from energy_pilot.carspeed import decide

F = {"plug": True, "house": 500, "battery": 0, "grid": 0, "ev": 0}
S = {"charger_kw": 11, "charger_phases": 3, "ev_follow_sun": True}


def flow(pv):
    return {**F, "pv": pv}


def test_no_switch_without_setting():
    d = decide(flow(2500), S, False, False, 10, False)  # 2 kW surplus: too little for 3 phases
    assert d["charge"] is False and d["phases"] is None


def test_small_surplus_one_phase():
    s = {**S, "phase_switch": True, "phase_now": 3}
    d = decide(flow(2500), s, False, False, 10, False)  # 2 kW surplus
    assert d["charge"] and d["phases"] == 1 and d["current"] == 8


def test_big_surplus_three_phases():
    s = {**S, "phase_switch": True, "phase_now": 1}
    d = decide(flow(6000), s, False, False, 10, True)  # 5.5 kW surplus
    assert d["charge"] and d["phases"] == 3 and d["current"] == 7


def test_lock_keeps_phase():
    s = {**S, "phase_switch": True, "phase_now": 1, "phase_lock": True}
    d = decide(flow(6000), s, False, False, 10, True)
    assert d["phases"] == 1 and d["current"] == 16  # 1 phase, capped at the charger's 16 A per phase


def test_planned_and_manual_full_three_phases():
    s = {**S, "phase_switch": True, "phase_now": 1}
    assert decide(flow(0), s, True, False, 10, False)["phases"] == 3
    assert decide(flow(2500), s, False, True, 10, False)["phases"] == 3


def test_sun_only_never_from_grid_but_charge_now_works():
    s = {**S, "ev_mode": "solar"}
    d = decide(flow(1000), s, True, False, 10, False)  # planned sunny hour, but a cloud: 0.5 kW surplus
    assert d["charge"] is False and d["why"] == "sun_only"
    assert decide(flow(1000), s, True, True, 10, False)["charge"] is True  # "charge now"
    assert decide(flow(6000), s, True, False, 10, False)["why"] == "sun"


def test_cheapest_mode_unchanged():
    d = decide(flow(1000), S, True, False, 10, False)
    assert d["charge"] and d["why"] == "planned" and d["current"] == 16


def test_phase_control_found():
    st = {"select.evcc_garage_phases_configured": {"state": "3", "attributes": {"options": ["0", "1", "3"]}},
          "select.goe_psm": {"state": "Force_3", "attributes": {"options": ["Auto", "Force_1", "Force_3"]}}}
    pc = phase_control(["select.evcc_garage_phases_configured"], st)
    assert pc == {"entity": "select.evcc_garage_phases_configured", "1": "1", "3": "3", "now": 3}
    st["select.goe_phase_switch_mode"] = st.pop("select.goe_psm")
    pc = phase_control(["select.goe_phase_switch_mode"], st)
    assert pc["1"] == "Force_1" and pc["3"] == "Force_3" and pc["now"] == 3
    assert phase_control(["select.evcc_garage_mode"], st) is None

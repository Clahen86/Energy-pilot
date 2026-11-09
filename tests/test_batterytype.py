"""The battery's kind is found by itself, and sets the wear, the lowest level and the efficiency."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from energy_pilot import batterytype as bt
from energy_pilot.engine import Battery, Hour, plan_battery


def test_found_from_inverter_setting_model_and_efficiency():
    lead = {"select.deye_battery_type": {"state": "Lead-acid", "attributes": {}}}
    assert bt.detect(lead, None, None, None)["type"] == "lead"
    assert bt.detect({}, "BYD Battery-Box Premium HVS", None, None) == {"type": "lfp", "why": "model", "cycles": None}
    assert bt.detect({}, "Tesla Powerwall 2", None, None)["type"] == "nmc"
    assert bt.detect({}, "Tesla Powerwall 3", None, None)["type"] == "lfp"
    assert bt.detect({}, None, None, 0.79, 5)["type"] == "lead"
    soc = {"sensor.deye_battery": {"state": "40", "attributes": {"Life Cycle Rating": 6000}}}
    assert bt.detect(soc, None, "sensor.deye_battery", None)["cycles"] == 6000
    assert bt.detect({}, "Growatt SPH", None, None) == {"type": "lfp", "why": "default", "cycles": None}


def test_wear_from_type_or_price():
    assert bt.wear("lfp", "DKK") == 0.133  # 1600 kr/kWh over 6000 cycles, both ways
    assert bt.wear("lead", "DKK") == 0.5
    assert bt.wear("lfp", "DKK", 10, 12000) == 0.1  # paid 12000 kr for 10 kWh
    assert 0.015 < bt.wear("lfp", "EUR") < 0.02


def test_wear_stops_cycling_for_crumbs():
    t0 = datetime(2026, 11, 9, 0, tzinfo=ZoneInfo("Europe/Copenhagen"))
    # 2.00 at night, 2.30 by day: beats the losses (2.17) but not losses and wear (about 2.45)
    hours = [Hour(t0 + timedelta(hours=i), 2.0 if i < 6 else 2.30, 0.0, 1.0, 0.0) for i in range(24)]
    without = plan_battery(hours, 20, Battery(capacity_kwh=10, grid_charge=True, wear=0.0), end_value=1.8)
    assert any(s.action == "charge_grid" for s in without.steps)
    p = plan_battery(hours, 20, Battery(capacity_kwh=10, grid_charge=True, wear=0.133), end_value=1.8)
    assert not any(s.action == "charge_grid" for s in p.steps)

"""The inverter's AC power, read by itself: from the model's name or a rated-power sensor of its integration."""

from datetime import datetime, timedelta

from energy_pilot import invpower
from energy_pilot.engine import Battery, Hour, plan_battery


def test_models():
    cases = {"SolaX Power X1-Hybrid-5.0kW": 5.0, "SolarEdge  SE10K-RWS48BEN4": 10.0, "SE5000H": 5.0, "FoxESS H3-15.0-Smart - LAN": 15.0,
             "FoxESS H1-3.7-E-G2 - AUX": 3.7, "FoxESS H3-Pro-20.0 - AUX": 20.0, "Kostal PLENTICORE plus 7.0": 7.0, "GoodWe GW10KL-ET": 10.0,
             "AlphaESS SMILE5-INV": 5.0, "AlphaESS SMILE-G3-T10-INV": 10.0, "Sigenergy Sigen Hybrid 5.0 SP2": 5.0,
             "Deye SUN-12K-SG05LP3": 12.0, "Sunsynk 12kW Inverter (**2066)": 12.0, "MultiPlus-II 48/5000/70-50": 5.0,
             "Huawei SUN2000-8KTL-M1": 8.0, "Growatt SPH6000": 6.0}
    for model, kw in cases.items():
        assert invpower.from_model(model) == kw, model
    for model in ("Huawei Batteries", "SolarEdge Home Battery 13.8kWh", "Victron Energy SmartShunt 300A", "Deye SG0*LP1", None):
        assert invpower.from_model(model) is None, model


def test_rated_sensor_only_from_its_own_integration():
    states = {"sensor.inverter_rated_power": {"state": "8000", "attributes": {"unit_of_measurement": "W"}},
              "sensor.heat_pump_rated_power": {"state": "3", "attributes": {"unit_of_measurement": "kW"}}}
    assert invpower.from_states(states, {"sensor.inverter_rated_power"}) == 8.0
    assert invpower.from_states(states, None) is None


def test_plan_charges_from_grid_only_as_fast_as_the_ac_side():
    t0 = datetime(2026, 11, 25, 0, 0)
    hours = [Hour(t0 + timedelta(hours=i), 0.5 if i < 2 else 3.0, 0.0, 0.3, 0.1) for i in range(8)]
    big = Battery(capacity_kwh=20, max_charge_kw=10, max_discharge_kw=10, min_soc=10)
    small = Battery(capacity_kwh=20, max_charge_kw=10, max_discharge_kw=10, min_soc=10, ac_kw=3.0)
    a, b = plan_battery(hours, 10, big), plan_battery(hours, 10, small)
    assert b.steps[0].soc_end - b.steps[0].soc_start < a.steps[0].soc_end - a.steps[0].soc_start


def test_own_poor_day_without_solcast(tmp_path):
    from energy_pilot.learning import Learning

    L = Learning(tmp_path)
    assert L.sun_low() is None
    L.state["sun_days"] = [1.0, 0.9, 1.1, 0.4, 1.0, 0.95, 1.05, 0.5, 1.0, 1.0]
    assert L.sun_low() == 0.5
    from energy_pilot.engine import doubt_sun

    assert doubt_sun(2.0, 2.0, 2.0 * 0.5) < 2.0


def test_a_plenticore_generation_is_not_its_size():
    # "G3" is the generation: read as 3 kW it held a 45 kWh battery to 3 kW from the grid all night
    assert invpower.from_model("PLENTICORE L G3") is None
    assert invpower.from_model("PLENTICORE plus 7.0") == 7.0
    assert invpower.from_model("PLENTICORE G3 L 15") == 15.0
    assert invpower.from_model("Plenticore BI 10/26") == 10.0

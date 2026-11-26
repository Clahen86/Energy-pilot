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


def test_a_hybrids_sun_shares_the_ac_side_when_selling_from_the_battery():
    # A 10 kW hybrid with 8 kWh of sun in the dear hour: the battery can only add 2 kWh to it on the AC side. An
    # AC-coupled battery (its own inverter, ac_sun off) still sells its full 10 kW beside the sun.
    t0 = datetime(2026, 6, 25, 12, 0)
    hours = [Hour(t0, 1.0, 5.0, 0.0, 8.0), Hour(t0 + timedelta(hours=1), 1.0, 0.0, 0.0, 0.0)]
    kw = dict(capacity_kwh=40, max_charge_kw=12, max_discharge_kw=12, min_soc=10, efficiency=1.0, export=True, ac_kw=10.0)
    hybrid = plan_battery(hours, 80, Battery(ac_sun=True, **kw))
    coupled = plan_battery(hours, 80, Battery(**kw))
    sold = lambda p: (p.steps[0].soc_start - p.steps[0].soc_end) / 100 * 40  # noqa: E731
    assert sold(hybrid) <= 2.0 + 1e-6
    assert sold(coupled) > 2.0


def test_two_inverters_on_one_integration_take_the_batterys_own_rating():
    # Kostal: a Plenticore G3 with the battery and a Plenticore plus on the same integration, each with Inverter Max Power
    states = {"sensor.plenticore_l_g3_inverter_max_power": {"state": "15000", "attributes": {"unit_of_measurement": "W"}},
              "sensor.plenticore_plus_7_0_inverter_max_power": {"state": "6999", "attributes": {"unit_of_measurement": "W"}}}
    allowed = set(states)
    assert invpower.from_states(states, allowed) is None  # which one is it? not said
    assert invpower.from_states(states, allowed, {"sensor.plenticore_l_g3_inverter_max_power"}) == 15.0

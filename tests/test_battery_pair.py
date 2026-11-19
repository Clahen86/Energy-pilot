"""Fox ESS Modbus has two battery sensors that each show one way ("Battery Charge", "Battery Discharge", both 0 or
more). With one of them chosen, the power is charge less discharge - else charging looks like 0."""

from types import SimpleNamespace

from energy_pilot.overview import Overview


def ov(chosen, states):
    o = Overview.__new__(Overview)
    o.settings, o.engine = {"battery_sign": -1}, None
    o.ha = SimpleNamespace(states=states)
    o.role = lambda r: chosen if r == "battery_power" else None
    return o


def kw(v):
    return {"state": str(v), "attributes": {"unit_of_measurement": "kW"}}


def test_charge_less_discharge():
    st = {"sensor.battery_discharge": kw(0), "sensor.battery_charge": kw(4.2)}
    o = ov("sensor.battery_discharge", st)
    assert o.battery_pair() == ("sensor.battery_charge", "sensor.battery_discharge")
    assert o.battery_sign() == 1  # an old learned -1 no longer flips it
    st["sensor.battery_discharge"], st["sensor.battery_charge"] = kw(3.0), kw(0)
    assert ov("sensor.battery_charge", st).battery_pair() == ("sensor.battery_charge", "sensor.battery_discharge")


def test_one_signed_sensor_is_left_alone():
    assert ov("sensor.battery_discharge", {"sensor.battery_discharge": kw(1)}).battery_pair() is None  # no partner
    assert ov("sensor.growatt_battery_power", {"sensor.growatt_battery_power": kw(1)}).battery_pair() is None
    st = {"sensor.x_battery_discharge_power": kw(0), "sensor.x_battery_charge_power": kw(1)}
    assert ov("sensor.x_battery_discharge_power", st).battery_pair() == ("sensor.x_battery_charge_power", "sensor.x_battery_discharge_power")

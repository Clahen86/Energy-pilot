"""Fox ESS Modbus (and many others) have the grid as two one-way sensors: "Grid Consumption" and "Feed-in", or
"import" and "export" power. With only the buying one, selling never showed (a user in the UK: "Export not shown")."""

from types import SimpleNamespace

from energy_pilot.overview import Overview


def ov(chosen, states):
    o = Overview.__new__(Overview)
    o.settings, o.engine = {"grid_sign": -1}, None
    o.ha = SimpleNamespace(states=states)
    o.role = lambda r: chosen if r == "grid_power" else None
    return o


def kw(v):
    return {"state": str(v), "attributes": {"unit_of_measurement": "kW"}}


def test_buying_less_selling():
    for buy, sell in (("sensor.foxess_grid_consumption_power", "sensor.foxess_feed_in_power"),
                      ("sensor.foxess_grid_consumption_power_2", "sensor.foxess_feed_in_power_2"),
                      ("sensor.import_power", "sensor.export_power"),
                      ("sensor.inv_grid_import_power", "sensor.inv_grid_export_power")):
        o = ov(buy, {buy: kw(0), sell: kw(1.6)})
        assert o.grid_pair() == (buy, sell), buy
        assert o.grid_sign() == 1  # a sign set by hand earlier no longer flips it


def test_a_signed_meter_is_left_alone():
    assert ov("sensor.foxess_grid_consumption_power", {"sensor.foxess_grid_consumption_power": kw(0)}).grid_pair() is None
    st = {"sensor.energy_grid_import_export_power": kw(1), "sensor.energy_grid_export_export_power": kw(1)}
    assert ov("sensor.energy_grid_import_export_power", st).grid_pair() is None
    st = {"sensor.x_net_import_power": kw(1), "sensor.x_net_export_power": kw(1)}
    assert ov("sensor.x_net_import_power", st).grid_pair() is None
    assert ov("sensor.growatt_grid_power", {"sensor.growatt_grid_power": kw(1)}).grid_pair() is None

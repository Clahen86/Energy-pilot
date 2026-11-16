"""The session meter at plug-in: a KEBA keeps last time's number until the car starts charging."""

from energy_pilot import chargers


def _st(session, plug="on", s_changed="2026-11-16T22:17:09+00:00", p_changed="2026-11-16T22:17:08+00:00"):
    return {"sensor.s": {"state": str(session), "last_changed": s_changed},
            "binary_sensor.p": {"state": plug, "last_changed": p_changed}}


def test_old_number_after_restart_is_zero_with_mark():
    st = _st(19.84)  # a restart gave both a new last_changed
    assert chargers.session(st, "sensor.s", "binary_sensor.p") == 19.84  # without the mark: wrong
    assert chargers.session(st, "sensor.s", "binary_sensor.p", 19.84) == 0
    assert chargers.session(_st(2.5), "sensor.s", "binary_sensor.p", 19.84) == 2.5  # a new session from 0
    assert chargers.session(_st(25.0), "sensor.s", "binary_sensor.p", 19.84) == 5.16  # a meter that counts on
    assert chargers.session(_st(19.84, plug="off"), "sensor.s", "binary_sensor.p", 19.84) == 19.84


def test_mark_read_from_history(tmp_path):
    import asyncio

    from energy_pilot.overview import Overview

    class HA:
        states = {"binary_sensor.keba_p30_plug": {"state": "on", "attributes": {"device_class": "plug"}},
                  "sensor.keba_p30_session_energy": {"state": "19.84", "attributes": {"device_class": "energy", "unit_of_measurement": "kWh"}}}
        config = {"time_zone": "Europe/Copenhagen"}

        async def command(self, msg, timeout=60):
            if msg["entity_ids"] == ["binary_sensor.keba_p30_plug"]:
                return {"binary_sensor.keba_p30_plug": [{"s": "off", "lu": 1794605655.3}, {"s": "on", "lu": 1794854168.1}]}
            return {"sensor.keba_p30_session_energy": [{"s": "19.84", "lu": 1794854168.1}]}

    o = Overview(HA(), tmp_path)
    asyncio.run(o.async_plug_marks())
    assert o.settings["plug_marks"] == {"binary_sensor.keba_p30_plug": 19.84}
    assert o.ev()["session_kwh"] == 0

"""Controls written to the inverter's registers when its Solarman definition has no entity for them (#60, ZCS 3000SP)."""

import asyncio
from types import SimpleNamespace

from energy_pilot import adapters, registers

CTX = {"min_soc": 10, "soc": 62, "target": 90, "power_w": 2400, "max_charge_w": 3000, "now_from": "07:30",
       "now_to": "09:00", "grid_charge": True, "charge_a": 50}
SOFAR_OK = {0x1200: 0, 0x1201: 0, 0x1202: 0, 0x1203: 0x1600, 0x1204: 0x1700, 0x1205: 1500, 0x1206: 0}
SERIAL = {0x2001 + i: int.from_bytes(b"ZM1ES030AB1234"[2 * i:2 * i + 2], "big") for i in range(7)}
SOFAR_OK.update(SERIAL)


def test_every_register_control_is_a_control_of_its_profile():
    for key, variants in registers.MAPS.items():
        p = adapters.PROFILES[key]
        pats = {s[0] for i in ("normal", "hold", "charge", "export") for s in p.get(i, [])}
        for v in variants:
            assert set(v["controls"]) <= pats, (key, set(v["controls"]) - pats)
        need = {s[0] for i in ("normal", "hold", "charge") for s in p[i] if s[1] != "service"} - set(p.get("optional") or [])
        assert need <= set(variants[0]["controls"]), (key, need - set(variants[0]["controls"]))


def test_values_are_coded_as_davidrapans_definitions_write_them():
    me = registers.MAPS["sofar_me"][0]["controls"]
    assert registers.encode(me[r"time\..*timed_charge_start$"], "time", "07:30", CTX, None) == 0x071E
    assert registers.encode(me[r"number\..*timed_charge_power$"], "number", 4200, CTX, None) == 3000  # its max
    assert registers.encode(me[r"select\..*(?<!energy_pattern_)work_mode$"], "select", "Timed", CTX, None) == 2
    assert registers.encode(me[r"select\..*(?<!energy_pattern_)work_mode$"], "select", "Nonsense", CTX, None) is None
    h = registers.MAPS["solarman"][0]["controls"]
    # single phase Deye: only the programme's two source bits change
    assert registers.encode(h[r"select\..*program_1_charging$"], "select", "Grid", CTX, 0b1100) == 0b1101
    assert registers.encode(h[r"switch\..*battery_grid_charging$"], "grid", None, {"grid_charge": False}, None) == 0
    # selling and the charge current are never written by register (nothing to put them back from)
    assert r"number\..*export_surplus_power$" not in h and r"number\..*battery_grid_charging_current$" not in h


def test_only_registers_that_fit_are_used():
    assert registers.pick("sofar_me", SOFAR_OK)["definition"].startswith("Sofar HYD")
    assert registers.pick("sofar_me", {**SOFAR_OK, 0x1200: 9}) is None  # no such Work Mode: another register map
    assert registers.pick("sofar_me", {**SOFAR_OK, 0x1201: 0x1A00}) is None  # 26:00 is no time
    assert registers.pick("sofar_me", {k: v for k, v in SOFAR_OK.items() if k != 0x1206}) is None  # not all read
    zeros = {a: 0 for a in SOFAR_OK}
    assert registers.pick("sofar_me", zeros) is None  # seven zeros and no serial number: could be anything
    assert registers.pick("sofar_me", SOFAR_OK, known_serial="ZM1ES030AB1234") is not None
    assert registers.pick("sofar_me", SOFAR_OK, known_serial="SOMETHINGELSE") is None  # another inverter
    deye = {a: 0 for a in registers.addresses(registers.MAPS["solarman"][1])}
    assert registers.pick("solarman", {**deye, 0x0000: 0x0500})["definition"] == "Deye P3 (three phase)"
    assert registers.pick("solarman", {**deye, 0x0000: 0x0002}) is None  # an unknown type: never
    assert registers.pick("solarman", {**deye, 0x0000: 0x0104}) is None  # Deye's storage-only type: never
    assert registers.blocks([0x1200, 0x1201, 0x1206, 0x0000]) == [(0x0000, 1), (0x1200, 7)]


def test_hold_and_charge_by_register():
    p = adapters.PROFILES["sofar_me"]
    regs = {"controls": registers.MAPS["sofar_me"][0]["controls"], "raw": SOFAR_OK, "device": "dev1", "field": "address"}
    chk = adapters.check({i: p[i] for i in ("normal", "hold", "charge")}, [], [], None, regs)
    assert adapters.missing(chk) == [] and chk["normal"]["found"][0]["entity"] == "register 0x1200"
    calls = adapters.resolve(p["charge"], [], CTX, regs)
    assert all(c["domain"] == "solarman" and c["service"] == "write_multiple_registers" for c in calls)
    writes = [(c["data"]["address"], c["data"]["values"][0]) for c in calls]
    assert writes[-1] == (0x1200, 2)  # the mode last, as the profile says
    assert (0x1201, 0x071E) in writes and (0x1205, 2400) in writes
    old = adapters.resolve(p["normal"], [], CTX, {**regs, "field": "register"})
    assert old == [{"domain": "solarman", "service": "write_multiple_registers", "data": {"device": "dev1", "register": 0x1200, "values": [0]}}]
    # an entity that is there is still used, not the register
    assert adapters.resolve(p["normal"], ["select.zcs_work_mode"], CTX, regs)[0]["data"]["entity_id"] == "select.zcs_work_mode"


def test_the_zcs_from_issue_60_gets_its_own_profile_and_writes_registers():
    """ZCS 3000SP with a personalized Solarman YAML (no Work Mode select), Sofar G3 kept from an older version."""
    from energy_pilot import control as C

    saved = {}
    reads = []

    async def call_service(domain, service, data, response=False):
        reads.append(data)
        start = data["address"]
        return {"response": {str(a): SOFAR_OK.get(a, 0) for a in range(start, start + data["count"])}}

    c = C.Controller.__new__(C.Controller)
    c.ha = SimpleNamespace(states={}, call_service=call_service)
    c.ov = SimpleNamespace(settings={"inverter_profile": "sofar"}, save=lambda d, who: (saved.update(d), c.ov.settings.update(d)))
    c.entities = {"battery": ["select.zcs_inverter_status"], "car": []}
    c.platforms = {"battery": "solarman", "car": None}
    c.model = "MIO zcs"
    c.battery_device = "dev1"
    c.services = {registers.SOLARMAN_READ, registers.SOLARMAN_WRITE}
    c.service_fields = {registers.SOLARMAN_READ: {"device", "address", "count"}, registers.SOLARMAN_WRITE: {"device", "address", "values"}}
    c.bat_info = {}
    asyncio.run(c._read_registers())
    assert "sofar_me" in c.regs and reads[0] == {"device": "dev1", "address": 0x2001, "count": 7}  # its serial first
    c._mend_wrong_profile()
    assert saved == {"inverter_profile": "sofar_me"}
    assert adapters.missing(c.check()) == [] and c.missing_help() is None
    calls = adapters.resolve(adapters.PROFILES["sofar_me"]["hold"], c._pool(), CTX, c.regs_for())
    assert calls and calls[-1]["data"] == {"device": "dev1", "address": 0x1200, "values": [2]}


def test_registers_that_dont_fit_say_what_to_do():
    from energy_pilot import control as C

    async def call_service(domain, service, data, response=False):
        return {"response": {str(a): 99 for a in range(data["address"], data["address"] + data["count"])}}

    c = C.Controller.__new__(C.Controller)
    c.ha = SimpleNamespace(states={}, call_service=call_service)
    c.ov = SimpleNamespace(settings={"inverter_profile": "sofar"}, save=lambda d, who: None)
    c.entities = {"battery": ["select.zcs_inverter_status"], "car": []}
    c.platforms = {"battery": "solarman", "car": None}
    c.model = "MIO zcs"
    c.battery_device = "dev1"
    c.services = {registers.SOLARMAN_READ, registers.SOLARMAN_WRITE}
    c.service_fields = {}
    c.bat_info = {}
    asyncio.run(c._read_registers())
    assert c.regs == {}
    h = c.missing_help()
    assert h["name"].startswith("Sofar ME 3000-SP") and h["other"] and "Work Mode" in h["missing"]
    assert h["definition"] == "Sofar HYD 3000~6000-ES | ME 3000-SP"


def test_a_sofar_g3_with_all_its_controls_is_never_read_by_register():
    from energy_pilot import control as C

    reads = []

    async def call_service(domain, service, data, response=False):
        reads.append(data)
        return {"response": {str(a): 0 for a in range(data["address"], data["address"] + data["count"])}}

    g3 = ["select.inverter_storage_control_mode", "number.inverter_passive_minimum_battery_power",
          "number.inverter_passive_maximum_battery_power"]
    c = C.Controller.__new__(C.Controller)
    c.ha = SimpleNamespace(states={}, call_service=call_service)
    c.ov = SimpleNamespace(settings={}, save=lambda d, who: None)
    c.entities = {"battery": g3, "car": []}
    c.platforms = {"battery": "solarman", "car": None}
    c.model = "Sofar HYD 6000-EP"
    c.battery_device = "dev1"
    c.services = {registers.SOLARMAN_READ, registers.SOLARMAN_WRITE}
    c.service_fields = {}
    c.bat_info = {}
    asyncio.run(c._read_registers())
    assert reads == [] and c.regs == {} and c.profile_key() == "sofar"


def _deye_ctl(call_service):
    from energy_pilot import control as C

    h = registers.MAPS["solarman"][0]
    c = C.Controller.__new__(C.Controller)
    c.ha = SimpleNamespace(states={}, call_service=call_service)
    c.ov = SimpleNamespace(settings={"inverter_profile": "solarman"}, save=lambda d, who: None)
    c.entities = {"battery": ["select.other_inverter_program_1_charging", "number.mine_program_1_soc"], "car": []}
    c._ent_reg = {"select.other_inverter_program_1_charging": {"device_id": "devB"}, "number.mine_program_1_soc": {"device_id": "devA"}}
    c.platforms = {"battery": "solarman", "car": None}
    c.model = "Deye SUN-6K-SG03LP1"
    c.battery_device = "devA"
    c.service_fields = {}
    c.regs = {"solarman": {"controls": h["controls"], "raw": {}, "device": "devA", "field": "address", "definition": h["definition"]}}
    return c


def test_shared_bits_are_read_just_before_they_are_written():
    async def call_service(domain, service, data, response=False):
        return {"response": {str(data["address"]): 0b1100}}

    c = _deye_ctl(call_service)
    write = {"domain": "solarman", "service": "write_multiple_registers", "data": {"device": "devA", "address": 0x0112, "values": [1]}}
    assert asyncio.run(c._fresh_bits([write]))[0]["data"]["values"] == [0b1101]

    async def fails(domain, service, data, response=False):
        raise RuntimeError("offline")

    assert asyncio.run(_deye_ctl(fails)._fresh_bits([write])) == []  # not read: not written - never old bits back


def test_by_register_only_this_inverters_own_controls():
    c = _deye_ctl(None)
    assert c._pool() == ["number.mine_program_1_soc"]  # the second inverter's control is never mixed in

"""What a critical review found (Facebook, 2026-11-23): data only with a yes, changes only from the panel, a password in
Docker, and shared fixes that can never turn charging into selling."""

import base64
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from energy_pilot.control import safe_shared_fix
from energy_pilot.telemetry import Telemetry
from energy_pilot.web import _auth_ok, guard, panel_password


def test_shared_fix_never_turns_charging_into_selling():
    assert not safe_shared_fix("charge", "Forced charge", "Forced discharge")
    assert not safe_shared_fix("hold", "Stop (default)", "Export first")
    assert not safe_shared_fix("export", "Forced discharge", "Forced charge")
    assert not safe_shared_fix("charge", "Charge", "Off-grid")
    assert safe_shared_fix("charge", "Forced charge", "Force Charge")
    assert safe_shared_fix("export", "Forced discharge", "Force discharge")
    assert safe_shared_fix("normal", "Self-consumption", "Self use")


def _tel(settings):
    t = Telemetry.__new__(Telemetry)
    t.ov, t.url = SimpleNamespace(settings=settings), "https://x"
    return t


def test_hour_by_hour_and_area_only_with_a_yes():
    assert not _tel({}).hours_on  # not answered: off
    assert not _tel({"share_hours": False}).hours_on
    assert _tel({"share_hours": True}).hours_on
    assert not _tel({"share_hours": True, "share_anonymous": False}).hours_on


def test_docker_gets_a_password_the_addon_not(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "x")
    assert panel_password(tmp_path) is None
    monkeypatch.delenv("SUPERVISOR_TOKEN")
    monkeypatch.delenv("EP_PASSWORD", raising=False)
    pw = panel_password(tmp_path)
    assert pw and panel_password(tmp_path) == pw  # made once, kept
    monkeypatch.setenv("EP_PASSWORD", "mine")
    assert panel_password(tmp_path) == "mine"
    ok = "Basic " + base64.b64encode(b"any:mine").decode()
    assert _auth_ok(ok, "mine") and not _auth_ok("Basic " + base64.b64encode(b"any:no").decode(), "mine") and not _auth_ok(None, "mine")


@pytest.mark.asyncio
async def test_changes_only_as_json_and_with_the_password():
    async def handler(_req):
        return web.Response(text="ok")

    mw = guard(None, addon=False)
    form = make_mocked_request("POST", "/api/control", headers={"Content-Type": "text/plain"})
    assert (await mw(form, handler)).status == 415  # what a page elsewhere could send without asking
    js = make_mocked_request("POST", "/api/control", headers={"Content-Type": "application/json"})
    assert (await mw(js, handler)).status == 200
    assert (await mw(make_mocked_request("GET", "/api/overview"), handler)).status == 200
    locked = guard("pw", addon=False)
    assert (await locked(make_mocked_request("GET", "/"), handler)).status == 401
    auth = {"Authorization": "Basic " + base64.b64encode(b"x:pw").decode()}
    assert (await locked(make_mocked_request("GET", "/", headers=auth), handler)).status == 200


@pytest.mark.asyncio
async def test_addon_only_from_home_assistant_and_ingress():
    async def handler(_req):
        return web.Response(text="ok")

    mw = guard(None, addon=True)
    for ip, code in (("172.30.32.1", 200), ("172.30.32.2", 200), ("172.30.33.5", 403), ("192.168.1.20", 403)):
        req = make_mocked_request("GET", "/api/overview", transport=SimpleNamespace(get_extra_info=lambda k, d=None, ip=ip: (ip, 0) if k == "peername" else d))
        assert (await mw(req, handler)).status == code, ip


def test_hacs_copy_is_never_overwritten(tmp_path, monkeypatch):
    from energy_pilot import companion

    target = tmp_path / "custom_components" / "energy_pilot"
    monkeypatch.setattr(companion, "TARGET", target)
    assert companion.status() == "none"
    assert companion.install() and companion.status() == "app"
    (target / companion.HACS_MARK).write_text("")
    (target / "manifest.json").write_text("{}")  # HACS' own version
    assert companion.status() == "hacs" and not companion.install()
    assert (target / "manifest.json").read_text() == "{}"

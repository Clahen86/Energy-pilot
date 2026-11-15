"""Dashboard dependencies install together and invalidate the browser cache together."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from energy_pilot import cards


@pytest.mark.asyncio
async def test_artwork_install_and_dependency_cache_version(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "art").mkdir()
    (source / "art" / "house.png").write_bytes(b"house-v1")
    (source / "energy-scene.js").write_text("export const art = 1;")
    card = source / "energipilot-card.js"
    card.write_text('import { art } from "./energy-scene.js";')
    config = tmp_path / "ha"
    config.mkdir()
    monkeypatch.setattr(cards, "CARD", card)
    monkeypatch.setattr(cards, "HA_CONFIG", config)
    ha = SimpleNamespace(command=AsyncMock(return_value=[]))
    c = cards.Cards(ha, None, "test")
    await c.install()
    target = config / "www" / "energipilot"
    assert (target / "art" / "house.png").read_bytes() == b"house-v1"
    assert (target / "energy-scene.js").read_text() == "export const art = 1;"
    url1 = ha.command.call_args.args[0]["url"]
    stamp = url1.split("?v=")[1]
    assert f'./energy-scene.js?v={stamp}' in (target / card.name).read_text()

    ha.command.reset_mock()
    ha.command.return_value = [{"id": "test", "url": url1}]
    await c.install()
    assert ha.command.await_count == 1  # unchanged: no resource mutation

    (source / "art" / "house.png").write_bytes(b"house-v2")
    await c.install()
    url2 = ha.command.call_args.args[0]["url"]
    assert url2 != url1
    assert (target / "art" / "house.png").read_bytes() == b"house-v2"


@pytest.mark.asyncio
async def test_missing_dependency_leaves_existing_card_and_resource_alone(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    card = source / "energipilot-card.js"
    card.write_text('import "./energy-scene.js";')
    target = tmp_path / "www" / "energipilot"
    target.mkdir(parents=True)
    (target / card.name).write_text("previous working card")
    monkeypatch.setattr(cards, "CARD", card)
    monkeypatch.setattr(cards, "HA_CONFIG", tmp_path)
    ha = SimpleNamespace(command=AsyncMock())
    await cards.Cards(ha, None, "test").install()
    assert (target / card.name).read_text() == "previous working card"
    ha.command.assert_not_awaited()

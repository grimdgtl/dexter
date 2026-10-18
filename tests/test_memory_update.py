from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from dexter import memory
from dexter.tools import registry


@pytest.mark.parametrize(
    "args",
    [
        {"id": 1},
        {"id": 0, "tekst": "Proba"},
        {"id": True, "tekst": "Proba"},
        {"id": 1, "tekst": " "},
        {"id": 1, "kategorija": "izmišljeno"},
        {"id": 1, "tekst": "Proba", "embedding": [1]},
    ],
)
async def test_update_validates_before_database(monkeypatch, args):
    update = AsyncMock()
    monkeypatch.setattr(memory, "update", update)
    assert (await registry.execute("memory_update", args)).is_error
    update.assert_not_awaited()


async def test_missing_fact_is_not_created_or_embedded(monkeypatch):
    database = SimpleNamespace(fetchval=AsyncMock(return_value=False), fetchrow=AsyncMock())
    monkeypatch.setattr(memory, "pool", lambda: database)
    embed = AsyncMock()
    monkeypatch.setattr(memory, "embed_one", embed)
    out = await registry.execute("memory_update", {"id": 123, "tekst": "Proba"})
    assert out.is_error and "Nema činjenice" in out.text
    embed.assert_not_awaited()
    database.fetchrow.assert_not_awaited()


async def test_embedding_failure_leaves_existing_fact_untouched(monkeypatch):
    database = SimpleNamespace(fetchval=AsyncMock(return_value=True), fetchrow=AsyncMock())
    monkeypatch.setattr(memory, "pool", lambda: database)
    monkeypatch.setattr(
        memory, "embed_one", AsyncMock(side_effect=RuntimeError("Embed nije dostupan"))
    )
    out = await registry.execute("memory_update", {"id": 123, "tekst": "Proba"})
    assert out.is_error
    database.fetchrow.assert_not_awaited()

from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from dexter.config import Settings
from dexter.rag.chunking import chunk_text
from scripts import reindex_all


@pytest.mark.parametrize("size,overlap", [(0, 0), (100, 100), (200, -1)])
def test_invalid_chunk_settings(size, overlap):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, chunk_chars=size, chunk_overlap=overlap)


def test_chunking_uses_settings_and_keeps_long_words(monkeypatch):
    from dexter.config import settings

    monkeypatch.setattr(settings(), "chunk_chars", 600)
    monkeypatch.setattr(settings(), "chunk_overlap", 100)
    chunks = chunk_text("A" * 2400, title="Naslov")
    assert len(chunks) > 3
    assert all(c.startswith("Naslov\n") and len(c) <= 607 for c in chunks)
    assert sum(c.count("A") for c in chunks) >= 2400
    with pytest.raises(ValueError):
        chunk_text("tekst", size=10, overlap=10)


async def test_reindex_script_always_closes_database(monkeypatch):
    monkeypatch.setattr(reindex_all.db, "connect", AsyncMock())
    close = AsyncMock()
    monkeypatch.setattr(reindex_all.db, "close", close)
    monkeypatch.setattr(
        reindex_all, "reindex_all", AsyncMock(side_effect=ValueError("Nema teksta"))
    )
    with pytest.raises(ValueError):
        await reindex_all.run()
    close.assert_awaited_once()

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from apu.rag import rerank
from apu.rag.store import Hit


def hits():
    return [Hit(i, f"doc:{i}", "Назив", None, "Текст", 0.02) for i in range(3)]


def response(text, stop="end_turn"):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason=stop)


async def test_valid_rerank_uses_fast_model_without_tools(monkeypatch):
    create = AsyncMock(return_value=response("[2,0,1]"))
    monkeypatch.setattr(rerank.llm, "create", create)
    result = await rerank.rerank("Питање", hits())
    assert [h.chunk_id for h in result] == [2, 0, 1]
    call = create.await_args.kwargs
    assert "tools" not in call and call["purpose"] == "rerank"
    assert call["model"] == rerank.settings().model_fast
    assert "Naziv" in call["messages"][0]["content"] and "Pitanje" in call["messages"][0]["content"]


@pytest.mark.parametrize(
    "text,stop",
    [
        ("[1,1,0]", "end_turn"),
        ("[0,1,8]", "end_turn"),
        ("[true,0,2]", "end_turn"),
        ("[2]", "end_turn"),
        ("{}", "end_turn"),
        ("nije json", "end_turn"),
        ("[2,0,1]", "max_tokens"),
    ],
)
async def test_invalid_rerank_keeps_hybrid_order(monkeypatch, text, stop):
    monkeypatch.setattr(rerank.llm, "create", AsyncMock(return_value=response(text, stop)))
    original = hits()
    assert await rerank.rerank("Upit", original) == original


async def test_rerank_timeout_and_cancellation(monkeypatch):
    async def slow(**kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(rerank, "TIMEOUT_SECONDS", 0.001)
    monkeypatch.setattr(rerank.llm, "create", slow)
    original = hits()
    assert await rerank.rerank("Upit", original) == original
    monkeypatch.setattr(rerank.llm, "create", AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        await rerank.rerank("Upit", original)

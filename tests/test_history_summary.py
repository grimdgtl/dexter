"""Sažetak pomaže razgovoru, ali njegov neuspeh ne sme da blokira novu poruku."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from dexter.agent import summary
from dexter.agent.prompts import turn_context


def test_summary_entries_preserve_confirmation_outcomes_without_memory_or_image_bytes():
    content = [
        {
            "type": "text",
            "text": turn_context([{"id": 1, "text": "STARA_MEMORIJA"}], notes=["Otkazano slanje."]),
        },
        {"type": "image", "source": {"data": "BASE64_TAJNA"}},
        {"type": "text", "text": "Нови договор."},
    ]
    data = summary.entries([{"role": "user", "content": content}])
    assert "Otkazano slanje" in data[0] and "Novi dogovor" in data[0]
    assert "STARA_MEMORIJA" not in data[0] and "BASE64_TAJNA" not in data[0]


@pytest.mark.parametrize(
    "text,stop",
    [
        ("Deo odgovora", "max_tokens"),
        ("", "end_turn"),
        ("X" * 6001, "end_turn"),
    ],
)
async def test_invalid_summary_has_only_one_larger_retry(monkeypatch, text, stop):
    create = AsyncMock(
        return_value=SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)],
            stop_reason=stop,
        )
    )
    monkeypatch.setattr(summary.llm, "create", create)
    assert await summary.summarize_part("Prethodni sažetak", "Arhiva") is None
    assert [c.kwargs["max_tokens"] for c in create.call_args_list] == [1800, 3600]
    assert (
        create.call_args_list[0].kwargs["messages"] == create.call_args_list[1].kwargs["messages"]
    )


async def test_api_failure_does_not_retry_or_log_private_content(monkeypatch, caplog):
    create = AsyncMock(side_effect=RuntimeError("TAJNI_ODGOVOR_PROVAJDERA"))
    monkeypatch.setattr(summary.llm, "create", create)
    assert await summary.summarize_part("PRIVATNI_SAZETAK", "PRIVATNA_ARHIVA") is None
    create.assert_awaited_once()
    assert "RuntimeError" in caplog.text
    assert not any(
        text in caplog.text
        for text in (
            "TAJNI_ODGOVOR_PROVAJDERA",
            "PRIVATNI_SAZETAK",
            "PRIVATNA_ARHIVA",
        )
    )


async def test_summary_timeout_releases_request(monkeypatch):
    finished = []

    async def blocked(**kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            finished.append(True)

    monkeypatch.setattr(summary, "SUMMARY_TIMEOUT_S", 0.01)
    monkeypatch.setattr(summary.llm, "create", blocked)
    async with asyncio.timeout(1):
        assert await summary.summarize_part("", "Arhiva") is None
    assert finished == [True]


async def test_caller_cancellation_is_not_turned_into_fallback(monkeypatch):
    monkeypatch.setattr(summary.llm, "create", AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        await summary.summarize_part("", "Arhiva")

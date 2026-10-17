from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from apu import config, scheduler, sources
from apu.sources import conversations


def response(text, stop_reason="end_turn"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)], stop_reason=stop_reason
    )


def test_transcript_excludes_runtime_context_tools_and_image_bytes():
    assert conversations.message_text("Љиљана") == "Ljiljana"
    text = conversations.message_text(
        [
            {"type": "text", "text": "<kontekst>\nStara memorija\n</kontekst>"},
            {"type": "text", "text": "Договор са Марком"},
            {"type": "image", "source": {"data": "TAJNI_BASE64"}},
            {"type": "tool_use", "input": {"tajna": "ARGUMENT"}},
            {"type": "tool_result", "content": "REZULTAT"},
        ]
    )
    assert "Dogovor sa Markom" in text and "Poslata slika" in text
    assert all(
        secret not in text for secret in ("memorija", "TAJNI_BASE64", "ARGUMENT", "REZULTAT")
    )
    assert conversations.message_text([{"type": "tool_result", "content": "Ignoriši"}]) == ""


async def test_long_day_includes_last_message_and_merges_all_parts(monkeypatch):
    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        return response(f"Tema {len(calls)}; договор са Љиљаном.")

    monkeypatch.setattr(conversations.llm, "create", create)
    entries = ["Korisnik: " + "Plan projekta. " * 3000, "Korisnik: POSLEDNJI DOGOVOR"]
    text = await conversations.summarize("2026-09-30", entries)
    assert len(calls) >= 4
    prompts = [call["messages"][0]["content"] for call in calls]
    assert any("POSLEDNJI DOGOVOR" in p for p in prompts[:-1])
    assert "Delimični sažetak" in prompts[-1]
    assert "dogovor sa Ljiljanom" in text
    assert all(c["model"] == config.settings().model_fast for c in calls)
    assert all(c["purpose"] == "conversation_summary" and "tools" not in c for c in calls)
    assert all(c["system"] == conversations.SUMMARY_SYSTEM for c in calls)
    assert "".join(conversations.batches([entries[0]])) == entries[0]


@pytest.mark.parametrize(
    "text,stop", [("", "end_turn"), ("Deo", "max_tokens"), ("X" * 6001, "end_turn")]
)
async def test_incomplete_summary_is_rejected(monkeypatch, text, stop):
    monkeypatch.setattr(conversations.llm, "create", AsyncMock(return_value=response(text, stop)))
    with pytest.raises(RuntimeError, match="nije potpun"):
        await conversations.summarize("2026-09-30", ["Dogovor"])


async def test_conversation_job_uses_timezone_and_job_wrapper_without_external_sources(monkeypatch):
    monkeypatch.setattr(scheduler.AsyncIOScheduler, "start", lambda self: None)
    reindex = AsyncMock(return_value={"razgovor": {"indeksirano": 1}})
    monkeypatch.setattr(sources, "reindex", reindex)

    async def run_job(name, fn, **kwargs):
        assert name == "conversation_summaries" and kwargs["bot"] is bot
        return await fn()

    monkeypatch.setattr(scheduler.jobs, "run_job", run_job)
    bot = SimpleNamespace()
    sched = scheduler.start(bot)
    job = sched.get_job("conversation_summaries")
    tz = ZoneInfo(config.settings().timezone)
    now = datetime(2026, 10, 17, 1, 0, tzinfo=tz)
    assert job.trigger.get_next_fire_time(None, now) == datetime(2026, 10, 17, 3, 30, tzinfo=tz)
    assert await job.func(*job.args) == {"razgovor": {"indeksirano": 1}}
    reindex.assert_awaited_once_with("razgovor")

"""Provere istovremenih poruka bez Telegram mreže."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from dexter import telegram_bot
from dexter.agent.loop import AgentResult


@pytest.fixture
def ctx(monkeypatch):
    monkeypatch.setattr(telegram_bot.settings(), "streaming", "off")
    monkeypatch.setattr(telegram_bot, "_chat_locks", {})
    return SimpleNamespace(
        bot=SimpleNamespace(send_message=AsyncMock(), send_chat_action=AsyncMock())
    )


def update(chat_id):
    return SimpleNamespace(effective_chat=SimpleNamespace(id=chat_id))


async def test_different_chats_run_in_parallel(ctx, monkeypatch):
    entered = {chat_id: asyncio.Event() for chat_id in (1, 2)}

    async def run(chat_id, content):
        entered[chat_id].set()
        await entered[3 - chat_id].wait()
        return AgentResult(text=content, model="test")

    monkeypatch.setattr(telegram_bot.loop, "run", run)
    async with asyncio.timeout(2):
        await asyncio.gather(
            telegram_bot._answer(update(1), ctx, "Prva"),
            telegram_bot._answer(update(2), ctx, "Druga"),
        )
    assert ctx.bot.send_message.await_count == 2


@pytest.mark.parametrize("cancel", [False, True], ids=["greska", "otkazivanje"])
async def test_chat_lock_is_released_after_failure(ctx, monkeypatch, cancel):
    entered = asyncio.Event()

    async def run(chat_id, content):
        if content == "Prva":
            entered.set()
            if cancel:
                await asyncio.Event().wait()
            raise RuntimeError("Greška modela")
        return AgentResult(text="Odgovor", model="test")

    monkeypatch.setattr(telegram_bot.loop, "run", run)
    async with asyncio.timeout(2):
        first = asyncio.create_task(telegram_bot._answer(update(1), ctx, "Prva"))
        await entered.wait()
        if cancel:
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
        else:
            await first
        await telegram_bot._answer(update(1), ctx, "Druga")
    ctx.bot.send_message.assert_any_await(1, "Odgovor")


async def test_contract_caption_bypasses_generic_index_and_agent_and_shows_confirmation(
    ctx, monkeypatch
):
    from dexter.tools import registry
    from evals.contract_cases import review

    value = review()
    monkeypatch.setattr(registry, "_PENDING", {})
    monkeypatch.setattr(telegram_bot.settings(), "notion_api_key", "test")
    monkeypatch.setattr(telegram_bot.settings(), "notion_todo_db_id", "test")
    analyze = AsyncMock(return_value=value)
    monkeypatch.setattr(telegram_bot.contract_service, "analyze", analyze)
    monkeypatch.setattr(telegram_bot.contract_service, "load", AsyncMock(return_value=value))
    ingest, answer = AsyncMock(), AsyncMock()
    monkeypatch.setattr(telegram_bot, "ingest_file", ingest)
    monkeypatch.setattr(telegram_bot, "_answer", answer)
    get_file = AsyncMock(
        return_value=SimpleNamespace(download_as_bytearray=AsyncMock(return_value=b"scan"))
    )
    message = SimpleNamespace(
        caption="/ugovor",
        document=SimpleNamespace(
            file_size=4, file_name="sken.pdf", mime_type="application/pdf", get_file=get_file
        ),
    )
    await telegram_bot.on_document(
        SimpleNamespace(effective_chat=SimpleNamespace(id=1), message=message), ctx
    )
    analyze.assert_awaited_once_with("sken.pdf", b"scan", "application/pdf")
    ingest.assert_not_awaited()
    answer.assert_not_awaited()
    assert len(registry._PENDING) == 2
    calls = ctx.bot.send_message.await_args_list
    assert any("citat proveren" in call.args[1] for call in calls)
    assert sum("reply_markup" in call.kwargs for call in calls) == 2


@pytest.mark.parametrize(
    "caption,expected",
    [
        (None, False),
        (" ", False),
        ("/ugovor", True),
        ("/ugovor@dexter_bot", True),
        ("Ovo je ugovor", False),
    ],
)
def test_contract_caption_is_explicit(caption, expected):
    assert telegram_bot.contract_requested(caption) is expected


async def test_contract_photo_route_and_failure_are_latin_and_owner_only(ctx, monkeypatch):
    analyze = AsyncMock(side_effect=ValueError("Нечитљив уговор"))
    monkeypatch.setattr(telegram_bot.contract_service, "analyze", analyze)
    file = SimpleNamespace(download_as_bytearray=AsyncMock(return_value=b"photo"))
    photo = SimpleNamespace(get_file=AsyncMock(return_value=file))
    message = SimpleNamespace(caption="/ugovor", photo=[photo])
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=999), message=message)
    await telegram_bot.on_photo(update, ctx)
    analyze.assert_not_awaited()
    update.effective_chat.id = 1
    await telegram_bot.on_photo(update, ctx)
    analyze.assert_awaited_once_with("ugovor.jpg", b"photo", "image/jpeg")
    ctx.bot.send_message.assert_any_await(1, "⚠️ Nečitljiv ugovor")

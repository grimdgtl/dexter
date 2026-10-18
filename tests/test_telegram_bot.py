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

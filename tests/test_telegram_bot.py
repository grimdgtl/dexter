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
    monkeypatch.setattr(telegram_bot.contract_intake, "arm", AsyncMock())
    monkeypatch.setattr(telegram_bot.contract_intake, "cancel", AsyncMock())
    monkeypatch.setattr(telegram_bot.contract_intake, "consume", AsyncMock(return_value=False))
    return SimpleNamespace(
        bot=SimpleNamespace(send_message=AsyncMock(), send_chat_action=AsyncMock())
    )


def update(chat_id):
    return SimpleNamespace(effective_chat=SimpleNamespace(id=chat_id))


async def test_failed_typing_status_does_not_fail_successful_answer(ctx, monkeypatch, caplog):
    entered = asyncio.Event()

    async def typing(*args):
        entered.set()
        raise RuntimeError("PRIVATNI_ODGOVOR_PROVAJDERA")

    async def run(*args):
        await entered.wait()
        return AgentResult(text="Odgovor je spreman.", model="test")

    ctx.bot.send_chat_action.side_effect = typing
    monkeypatch.setattr(telegram_bot.loop, "run", run)
    await telegram_bot._answer(update(1), ctx, "Pitanje")
    ctx.bot.send_message.assert_awaited_once_with(1, "Odgovor je spreman.")
    assert "Status kucanja nije dostupan (RuntimeError)" in caplog.text
    assert "PRIVATNI_ODGOVOR_PROVAJDERA" not in caplog.text


async def test_failed_typing_does_not_mask_agent_error(ctx, monkeypatch):
    entered = asyncio.Event()

    async def typing(*args):
        entered.set()
        raise RuntimeError("Status nije dostupan")

    async def run(*args):
        await entered.wait()
        raise ValueError("Greška agenta")

    ctx.bot.send_chat_action.side_effect = typing
    monkeypatch.setattr(telegram_bot.loop, "run", run)
    await telegram_bot._answer(update(1), ctx, "Pitanje")
    ctx.bot.send_message.assert_awaited_once_with(
        1, "⚠️ Nešto je puklo. Probaj ponovo za koji trenutak."
    )


async def test_typing_cancellation_is_preserved(ctx):
    ctx.bot.send_chat_action.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await telegram_bot._keep_typing(ctx.bot, 1, asyncio.Event())


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
    ctx, monkeypatch, contract_notion
):
    from dexter.tools import registry
    from evals.contract_cases import review

    value = review()
    monkeypatch.setattr(registry, "_PENDING", {})
    monkeypatch.setattr(telegram_bot.settings(), "notion_api_key", "test")
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


def contract_message(**kwargs):
    return SimpleNamespace(message_id=12, caption=None, reply_text=AsyncMock(), **kwargs)


def contract_document(**kwargs):
    values = dict(
        file_name="ugovor.pdf",
        mime_type="application/pdf",
        file_size=4,
        get_file=AsyncMock(
            return_value=SimpleNamespace(download_as_bytearray=AsyncMock(return_value=b"scan"))
        ),
    )
    return SimpleNamespace(**(values | kwargs))


async def test_standalone_contract_command_arms_next_file(ctx, monkeypatch):
    ctx.args = []
    value = update(1)
    value.message = contract_message()
    await telegram_bot.cmd_contract(value, ctx)
    telegram_bot.contract_intake.arm.assert_awaited_once_with(1, 12)
    assert "10 minuta" in value.message.reply_text.call_args.args[0]
    value.message = contract_message(document=contract_document())
    telegram_bot.contract_intake.consume.return_value = True
    review = AsyncMock()
    ingest = AsyncMock()
    monkeypatch.setattr(telegram_bot, "_contract_review", review)
    monkeypatch.setattr(telegram_bot, "ingest_file", ingest)
    await telegram_bot.on_document(value, ctx)
    review.assert_awaited_once_with(value, ctx, "ugovor.pdf", b"scan", "application/pdf")
    ingest.assert_not_awaited()


@pytest.mark.parametrize("kind", ["document", "photo"])
async def test_contract_command_as_reply_reads_replied_attachment(ctx, monkeypatch, kind):
    ctx.args = []
    doc = contract_document()
    source = SimpleNamespace(**({"document": doc} if kind == "document" else {"photo": [doc]}))
    value = update(1)
    value.message = contract_message(reply_to_message=source)
    review = AsyncMock()
    monkeypatch.setattr(telegram_bot, "_contract_review", review)
    await telegram_bot.cmd_contract(value, ctx)
    review.assert_awaited_once_with(
        value,
        ctx,
        "ugovor.pdf" if kind == "document" else "ugovor.jpg",
        b"scan",
        "application/pdf" if kind == "document" else "image/jpeg",
    )
    telegram_bot.contract_intake.arm.assert_not_awaited()
    telegram_bot.contract_intake.cancel.assert_awaited_once_with(1)


@pytest.mark.parametrize("mode", ["cancel", "id"])
async def test_contract_cancel_or_existing_review_clears_intake(ctx, monkeypatch, mode):
    ctx.args = ["otkazi" if mode == "cancel" else "review-id"]
    value = update(1)
    value.message = contract_message()
    show = AsyncMock()
    monkeypatch.setattr(telegram_bot, "_show_contract", show)
    monkeypatch.setattr(telegram_bot.contract_service, "load", AsyncMock(return_value="saved"))
    await telegram_bot.cmd_contract(value, ctx)
    telegram_bot.contract_intake.cancel.assert_awaited_once_with(1)
    assert show.await_count == (mode == "id")
    telegram_bot.contract_intake.arm.assert_not_awaited()


async def test_contract_command_and_pending_file_ignore_other_owner(ctx, monkeypatch):
    ctx.args = []
    value = update(999)
    value.message = contract_message(document=contract_document())
    await telegram_bot.cmd_contract(value, ctx)
    await telegram_bot.on_document(value, ctx)
    telegram_bot.contract_intake.arm.assert_not_awaited()
    telegram_bot.contract_intake.consume.assert_not_awaited()
    value.message.document.get_file.assert_not_awaited()


@pytest.mark.parametrize("fault", ["oversize", "unsupported", "download"])
async def test_pending_contract_errors_never_fall_back_to_generic_ingest(ctx, monkeypatch, fault):
    telegram_bot.contract_intake.consume.return_value = True
    doc = contract_document()
    if fault == "oversize":
        doc.file_size = telegram_bot.contract_service.MAX_BYTES + 1
    elif fault == "unsupported":
        doc.file_name, doc.mime_type = "test.docx", "application/other"
    else:
        doc.get_file.side_effect = RuntimeError("mreža")
    value = update(1)
    value.message = contract_message(document=doc)
    review, ingest = AsyncMock(), AsyncMock()
    monkeypatch.setattr(telegram_bot, "_contract_review", review)
    monkeypatch.setattr(telegram_bot, "ingest_file", ingest)
    await telegram_bot.on_document(value, ctx)
    review.assert_not_awaited()
    ingest.assert_not_awaited()
    value.message.reply_text.assert_awaited_once()
    if fault != "download":
        doc.get_file.assert_not_awaited()


async def test_pending_contract_photo_and_inactive_generic_file(ctx, monkeypatch):
    value = update(1)
    value.message = contract_message(photo=[contract_document()])
    telegram_bot.contract_intake.consume.return_value = True
    review, answer = AsyncMock(), AsyncMock()
    monkeypatch.setattr(telegram_bot, "_contract_review", review)
    monkeypatch.setattr(telegram_bot, "_answer", answer)
    await telegram_bot.on_photo(value, ctx)
    review.assert_awaited_once()
    answer.assert_not_awaited()
    telegram_bot.contract_intake.consume.return_value = False
    ingest = AsyncMock(return_value=(1, "Indeksirano"))
    monkeypatch.setattr(telegram_bot, "ingest_file", ingest)
    value.message = contract_message(document=contract_document())
    await telegram_bot.on_document(value, ctx)
    ingest.assert_awaited_once_with("ugovor.pdf", b"scan")
    assert review.await_count == 1


async def test_unknown_intake_state_does_not_index_or_download(ctx, monkeypatch):
    telegram_bot.contract_intake.consume.side_effect = RuntimeError("baza")
    value = update(1)
    value.message = contract_message(document=contract_document())
    ingest = AsyncMock()
    monkeypatch.setattr(telegram_bot, "ingest_file", ingest)
    await telegram_bot.on_document(value, ctx)
    ingest.assert_not_awaited()
    value.message.document.get_file.assert_not_awaited()
    assert "Ne mogu da proverim" in value.message.reply_text.call_args.args[0]

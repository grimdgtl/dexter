import asyncio
import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from dexter import llm, receipts, telegram_bot
from dexter.agent.loop import AgentResult
from dexter.tools import registry


def receipt_data(**changes):
    return {
        "prodavac": "Продавница",
        "pib": "123456789",
        "datum": "2026-10-17",
        "ukupno": "120.50",
        "pdv": "20.08",
        "valuta": "RSD",
        "stavke": [{"naziv": "Кафа", "kolicina": "1", "cena": "120.50", "iznos": "120.50"}],
        **changes,
    }


def image(data=b"slika racuna"):
    return [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.b64encode(data).decode(),
            },
        }
    ]


async def test_auto_tool_http_returns_validated_private_snapshot(
    monkeypatch, respx_mock, anthropic_client
):
    route = respx_mock.post("https://api.anthropic.com/v1/messages").respond(
        200,
        json={
            "id": "receipt",
            "type": "message",
            "role": "assistant",
            "model": "test",
            "content": [
                {"type": "tool_use", "id": "data", "name": "receipt_data", "input": receipt_data()}
            ],
            "stop_reason": "tool_use",
            "stop_sequence": None,
            "usage": {"input_tokens": 100, "output_tokens": 150},
        },
    )
    monkeypatch.setattr(llm, "client", lambda: anthropic_client)
    monkeypatch.setattr(llm.usage, "record", AsyncMock())
    with receipts.image_scope(image()):
        prepared = await receipts.prepare(receipts.ExtractArgs())
    assert prepared.model_dump() == {}
    assert prepared._receipt.prodavac == "Prodavnica"
    assert prepared._receipt.stavke[0].naziv == "Kafa"
    assert "120.50" in receipts.preview(prepared)
    body = json.loads(route.calls[0].request.content)
    assert body["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}
    assert [tool["name"] for tool in body["tools"]] == ["receipt_data"]
    assert body["messages"][0]["content"][0] == image()[0]
    assert llm.usage.record.await_args.args[1] == "receipt_extract"
    with pytest.raises(ValidationError):
        receipts.ExtractArgs.model_validate({"pib": "999999999", "_receipt": receipt_data()})
    with pytest.raises(ValueError, match="jednu sliku"):
        await receipts.prepare(receipts.ExtractArgs())


@pytest.mark.parametrize(
    "changes",
    [
        {"pib": "123"},
        {"ukupno": "NaN"},
        {"ukupno": "-1"},
        {"datum": "2026-02-30"},
        {"pdv": "999.99"},
        {"prodavac": " "},
        {"ukupno": "120.501"},
    ],
)
def test_receipt_rejects_inconsistent_or_invalid_data(changes):
    with pytest.raises(ValidationError):
        receipts.Receipt.model_validate(receipt_data(**changes))


async def test_preparation_failure_cannot_leave_pending_action(monkeypatch):
    monkeypatch.setattr(registry, "_PENDING", {})
    bad = SimpleNamespace(name="receipt_data", type="tool_use", input=receipt_data(datum=None))
    monkeypatch.setattr(
        llm,
        "create",
        AsyncMock(return_value=SimpleNamespace(content=[bad], stop_reason="tool_use")),
    )
    with receipts.image_scope(image()):
        result = await registry.execute("receipt_extract", {})
    assert result.is_error and not result.pending and not registry._PENDING


@pytest.mark.parametrize("response_kind", ["text", "wrong-tool", "multiple", "truncated"])
async def test_auto_receipt_without_one_complete_expected_tool_has_no_pending_action(
    monkeypatch, response_kind
):
    monkeypatch.setattr(registry, "_PENDING", {})
    block = SimpleNamespace(type="tool_use", name="receipt_data", input=receipt_data())
    content = [block]
    stop = "tool_use"
    if response_kind == "text":
        content, stop = [SimpleNamespace(type="text", text="Sažetak računa")], "end_turn"
    elif response_kind == "wrong-tool":
        block.name = "mail_send"
    elif response_kind == "multiple":
        content = [block, block]
    else:
        stop = "max_tokens"
    create = AsyncMock(return_value=SimpleNamespace(content=content, stop_reason=stop))
    monkeypatch.setattr(llm, "create", create)
    with receipts.image_scope(image()):
        result = await registry.execute("receipt_extract", {})
    assert result.is_error and result.pending is None and not registry._PENDING
    create.assert_awaited_once()


async def test_image_scope_is_isolated_and_text_does_not_reuse_previous_image():
    async def task(data):
        with receipts.image_scope(image(data)):
            await asyncio.sleep(0)
            return receipts._image.get()["source"]["data"]

    assert len(set(await asyncio.gather(task(b"prvi"), task(b"drugi")))) == 2
    with receipts.image_scope("Sačuvaj prethodni račun"):
        assert receipts._image.get() is None


async def test_long_confirmation_preview_keeps_all_data_and_buttons_last(monkeypatch):
    monkeypatch.setattr(telegram_bot.settings(), "streaming", "off")
    monkeypatch.setattr(
        telegram_bot.loop,
        "run",
        AsyncMock(
            return_value=AgentResult(
                "Nacrt čeka potvrdu.", "test", [("token", "Stavka računa\n" * 1000)]
            )
        ),
    )
    bot = SimpleNamespace(send_message=AsyncMock(), send_chat_action=AsyncMock())
    await telegram_bot._answer(
        SimpleNamespace(effective_chat=SimpleNamespace(id=1)), SimpleNamespace(bot=bot), "račun"
    )
    calls = bot.send_message.await_args_list
    assert all(len(c.args[1]) <= 4000 for c in calls)
    assert len(calls) > 3
    assert "reply_markup" in calls[-1].kwargs
    assert all("reply_markup" not in c.kwargs for c in calls[:-1])


async def test_expenses_command_is_owner_only_and_validates_month(monkeypatch):
    report = AsyncMock(return_value="Расходи за месец")
    monkeypatch.setattr(receipts, "report", report)
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=999), message=SimpleNamespace(reply_text=AsyncMock())
    )
    ctx = SimpleNamespace(args=["2026-10"])
    await telegram_bot.cmd_expenses(update, ctx)
    report.assert_not_awaited()
    update.effective_chat.id = 1
    await telegram_bot.cmd_expenses(update, ctx)
    report.assert_awaited_once_with("2026-10")
    update.message.reply_text.assert_awaited_once_with("Rashodi za mesec")


async def test_confirmation_failure_is_not_reported_as_success_and_fits_telegram(monkeypatch):
    monkeypatch.setattr(registry, "confirm", AsyncMock(return_value="Greška: baza nije dostupna."))
    monkeypatch.setattr(telegram_bot.history, "add_note", AsyncMock())
    query = SimpleNamespace(
        data="ok:token",
        message=SimpleNamespace(text="Pregled računa\n" * 300),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    bot = SimpleNamespace(send_message=AsyncMock())
    await telegram_bot.on_button(
        SimpleNamespace(effective_chat=SimpleNamespace(id=1), callback_query=query),
        SimpleNamespace(bot=bot),
    )
    displayed = [query.edit_message_text.await_args.args[0]] + [
        c.args[1] for c in bot.send_message.await_args_list
    ]
    assert all(len(t) <= 4000 for t in displayed)
    assert "Nije izvršeno" in "".join(displayed) and "✅ Izvršeno" not in "".join(displayed)

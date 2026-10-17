from itertools import pairwise
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from anthropic.types import Message

from apu import llm, telegram_bot
from apu.agent.loop import AgentResult


@pytest.fixture
def clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(telegram_bot, "time", SimpleNamespace(monotonic=lambda: now[0]))
    return now


async def test_stream_preview_throttles_edits_and_splits_latin_text(clock):
    sent = []
    edits = []

    async def send(chat, text):
        sent.append(text)
        return SimpleNamespace(message_id=len(sent))

    async def edit(text, **kwargs):
        edits.append((clock[0], text, kwargs))

    bot = SimpleNamespace(send_message=send, edit_message_text=edit)
    preview = telegram_bot.StreamingReply(bot, 1)
    await preview.update("Љ")
    await preview.update("Љубав")
    assert sent == ["Lj"] and not edits
    clock[0] = 1
    await preview.update("Љубав и мир")
    clock[0] = 1.2
    await preview.update("Љубав и мир свима")
    assert len(edits) == 1
    clock[0] = 2
    final = "Ljubav i mir svima " + "a" * 9000
    assert await preview.finish(final)
    assert all(len(s) <= telegram_bot.TG_LIMIT for s in sent)
    displayed = [preview.messages[i][1] for i in range(len(preview.messages))]
    assert "".join(displayed) == final
    assert all(b[0] - a[0] >= 1 for a, b in pairwise(edits))


async def test_stream_ui_failure_returns_to_final_delivery(clock):
    bot = SimpleNamespace(send_message=AsyncMock(side_effect=RuntimeError("Telegram")))
    preview = telegram_bot.StreamingReply(bot, 1)
    await preview.update("Tekst")
    assert not await preview.finish("Konačan tekst")


class FakeStream:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.current_message_snapshot = Message.model_validate(
            {
                "id": "test",
                "type": "message",
                "role": "assistant",
                "model": "test",
                "content": [{"type": "text", "text": "Одговор"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 100, "output_tokens": 5},
            }
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    @property
    def text_stream(self):
        async def parts():
            yield "Од"
            if self.fail:
                raise RuntimeError("Prekid streama")
            yield "говор"

        return parts()

    async def get_final_message(self):
        return self.current_message_snapshot


@pytest.mark.parametrize("fail", [False, True])
async def test_sdk_stream_counts_usage_once_including_interruption(monkeypatch, fail):
    stream = FakeStream(fail=fail)
    monkeypatch.setattr(
        llm,
        "client",
        lambda: SimpleNamespace(messages=SimpleNamespace(stream=lambda **kwargs: stream)),
    )
    record = AsyncMock()
    monkeypatch.setattr(llm.usage, "record", record)
    partial = AsyncMock()
    if fail:
        with pytest.raises(RuntimeError):
            await llm.stream(purpose="chat", on_text=partial, model="test")
    else:
        result = await llm.stream(purpose="chat", on_text=partial, model="test")
        assert llm.text_of(result) == "Одговор"
        assert partial.await_args.args[0] == "Одговор"
    record.assert_awaited_once()


async def test_telegram_stream_delivers_final_once_and_keeps_confirm_buttons(monkeypatch, clock):
    monkeypatch.setattr(telegram_bot.settings(), "streaming", "on")

    async def run(chat, content, *, on_text):
        await on_text("Одговор")
        return AgentResult("Одговор", "test", [("token", "Потврди акцију")])

    monkeypatch.setattr(telegram_bot.loop, "run", run)
    bot = SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=1)),
        edit_message_text=AsyncMock(),
        send_chat_action=AsyncMock(),
    )
    await telegram_bot._answer(
        SimpleNamespace(effective_chat=SimpleNamespace(id=1)), SimpleNamespace(bot=bot), "Poruka"
    )
    assert bot.send_message.await_count == 2
    assert bot.send_message.await_args_list[0].args[1] == "Odgovor"
    assert "reply_markup" in bot.send_message.await_args_list[1].kwargs


async def test_real_sdk_reads_sse_and_reports_final_usage(monkeypatch, respx_mock):
    import json

    import httpx
    from anthropic import AsyncAnthropic, _base_client

    sdk_http = getattr(_base_client, "httpx2", httpx)

    events = [
        {
            "type": "message_start",
            "message": {
                "id": "sse",
                "type": "message",
                "role": "assistant",
                "model": "test",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 100, "output_tokens": 0},
            },
        },
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Љубав"},
        },
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 5},
        },
        {"type": "message_stop"},
    ]
    data = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)
    respx_mock.post("https://api.anthropic.com/v1/messages").respond(
        200, text=data, headers={"content-type": "text/event-stream"}
    )

    def transport(request):
        response = respx_mock.handler(
            httpx.Request(request.method, str(request.url), content=request.content)
        )
        return sdk_http.Response(
            response.status_code, content=response.content, headers=response.headers
        )

    async with AsyncAnthropic(
        api_key="test",
        max_retries=0,
        http_client=sdk_http.AsyncClient(transport=sdk_http.MockTransport(transport)),
    ) as client:
        monkeypatch.setattr(llm, "client", lambda: client)
        record = AsyncMock()
        monkeypatch.setattr(llm.usage, "record", record)
        received = AsyncMock()
        result = await llm.stream(
            purpose="chat",
            on_text=received,
            model="test",
            max_tokens=20,
            messages=[{"role": "user", "content": "Pozdrav"}],
        )
        assert llm.text_of(result) == "Љубав"
        assert received.await_args.args[0] == "Љубав"
        assert record.await_args.args[0].input_tokens == 100
        assert record.await_args.args[0].output_tokens == 5
        record.assert_awaited_once()

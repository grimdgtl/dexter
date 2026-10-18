import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from dexter import telegram_bot, tts
from dexter.agent.loop import AgentResult
from dexter.config import settings


@pytest.mark.parametrize(
    "flag,voice_input,text,expected",
    [
        ("off", True, "Zdravo", False),
        ("on", True, "Zdravo", True),
        ("on", False, "Zdravo", False),
        ("off", False, "Odgovori glasom: koji je rok?", True),
        ("off", True, "Одговори ми гласом.", True),
        ("on", True, "Samo tekst, molim.", False),
        ("on", True, "Ne odgovaraj glasom.", False),
    ],
)
def test_voice_is_opt_in_or_explicit_and_can_be_disabled(
    monkeypatch, flag, voice_input, text, expected
):
    monkeypatch.setattr(settings(), "glas_odgovor", flag)
    assert tts.requested(text, voice_input=voice_input) is expected


async def test_tts_http_uses_latin_and_keeps_entire_long_answer_in_bounded_parts(
    monkeypatch, respx_mock
):
    monkeypatch.setattr(settings(), "openai_api_key", "test")
    monkeypatch.setattr(settings(), "tts_model", "gpt-4o-mini-tts")
    monkeypatch.setattr(settings(), "tts_voice", "coral")
    route = respx_mock.post("https://api.openai.com/v1/audio/speech").respond(
        200, content=b"OggS-opus-audio", headers={"Content-Type": "audio/opus"}
    )
    text = "Љубав и мир свима. " * 300
    chunks = [audio async for audio in tts.synthesize(text)]
    assert len(chunks) > 1 and len(chunks) == route.call_count
    bodies = [json.loads(call.request.content) for call in route.calls]
    assert " ".join(" ".join(b["input"] for b in bodies).split()) == " ".join(
        ("Ljubav i mir svima. " * 300).split()
    )
    assert all(len(b["input"].encode()) <= 1500 for b in bodies)
    assert all(b["response_format"] == "opus" and b["voice"] == "coral" for b in bodies)
    assert all("instructions" in b for b in bodies)
    assert route.calls[0].request.headers["Authorization"] == "Bearer test"


async def test_classic_tts_does_not_send_unsupported_instructions(monkeypatch, respx_mock):
    monkeypatch.setattr(settings(), "openai_api_key", "test")
    monkeypatch.setattr(settings(), "tts_model", "tts-1")
    route = respx_mock.post("https://api.openai.com/v1/audio/speech").respond(
        200, content=b"OggS-test"
    )
    assert [audio async for audio in tts.synthesize("Tekst")]
    assert "instructions" not in json.loads(route.calls[0].request.content)


@pytest.mark.parametrize("failure", ["missing_key", "http", "invalid_audio"])
async def test_tts_failures_are_visible_and_do_not_create_fake_voice(
    monkeypatch, respx_mock, failure
):
    monkeypatch.setattr(settings(), "openai_api_key", None if failure == "missing_key" else "test")
    if failure != "missing_key":
        respx_mock.post("https://api.openai.com/v1/audio/speech").respond(
            503 if failure == "http" else 200, content=b"not audio"
        )
    with pytest.raises((ValueError, httpx.HTTPStatusError)):
        _ = [audio async for audio in tts.synthesize("Odgovor")]


@pytest.mark.parametrize("streaming", ["on", "off"])
async def test_telegram_always_delivers_text_then_voice(monkeypatch, streaming):
    monkeypatch.setattr(settings(), "streaming", streaming)
    monkeypatch.setattr(settings(), "glas_odgovor", "on")
    actions = []

    async def run(*args, **kwargs):
        if kwargs.get("on_text"):
            await kwargs["on_text"]("Одговор")
        return AgentResult("Одговор", "test")

    async def speak(text):
        assert text == "Odgovor"
        yield b"OggS-test"

    async def send(chat, text, **kwargs):
        actions.append(("text", text))
        return SimpleNamespace(message_id=1)

    async def voice(chat, audio, **kwargs):
        actions.append(("voice", audio))
        assert audio.filename.endswith(".ogg") and "AI" in kwargs["caption"]

    monkeypatch.setattr(telegram_bot.loop, "run", run)
    monkeypatch.setattr(tts, "synthesize", speak)
    bot = SimpleNamespace(send_message=send, send_voice=voice, send_chat_action=AsyncMock())
    await telegram_bot._answer(
        SimpleNamespace(effective_chat=SimpleNamespace(id=1)),
        SimpleNamespace(bot=bot),
        "Poruka",
        voice_input=True,
    )
    assert [a[0] for a in actions] == ["text", "voice"]
    assert actions[0][1] == "Odgovor"


async def test_failed_voice_keeps_text_confirmation_buttons_and_history_result(monkeypatch):
    monkeypatch.setattr(settings(), "streaming", "off")
    monkeypatch.setattr(
        telegram_bot.loop,
        "run",
        AsyncMock(
            return_value=AgentResult(
                "Sačuvaj tek posle potvrde.", "test", [("token", "Račun za proveru")]
            )
        ),
    )

    async def fail(text):
        raise RuntimeError("TTS nije dostupan")
        yield b""

    monkeypatch.setattr(tts, "synthesize", fail)
    bot = SimpleNamespace(
        send_message=AsyncMock(), send_voice=AsyncMock(), send_chat_action=AsyncMock()
    )
    await telegram_bot._answer(
        SimpleNamespace(effective_chat=SimpleNamespace(id=1)),
        SimpleNamespace(bot=bot),
        "Odgovori glasom.",
    )
    calls = bot.send_message.await_args_list
    assert calls[0].args[1] == "Sačuvaj tek posle potvrde."
    assert "reply_markup" in calls[1].kwargs
    assert "Glasovni dodatak nije uspeo" in calls[2].args[1]
    bot.send_voice.assert_not_awaited()


async def test_voice_handler_passes_voice_origin_and_latin_transcript(monkeypatch):
    downloaded = SimpleNamespace(download_as_bytearray=AsyncMock(return_value=b"audio"))
    voice = SimpleNamespace(get_file=AsyncMock(return_value=downloaded))
    message = SimpleNamespace(voice=voice, audio=None, reply_text=AsyncMock())
    answer = AsyncMock()
    monkeypatch.setattr(telegram_bot, "transcribe", AsyncMock(return_value="Здраво"))
    monkeypatch.setattr(telegram_bot, "_answer", answer)
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=1), message=message)
    await telegram_bot.on_voice(update, SimpleNamespace())
    assert answer.await_args.kwargs["voice_input"] is True
    assert answer.await_args.args[2] == "Zdravo"
    message.reply_text.assert_awaited_once_with("🎙️ Zdravo")

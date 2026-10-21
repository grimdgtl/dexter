"""Mali izlazni limiti ne smeju nestati u razmišljanju niti prihvatiti delimičan tekst."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from dexter import budget, llm, usage


def response(text="", stop="end_turn"):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason=stop)


@pytest.mark.parametrize("purpose", sorted(llm.BACKGROUND_TEXT))
@pytest.mark.parametrize(
    "model,mode",
    [("claude-haiku-5-5", "disabled"), ("claude-sonnet-5-5", "between_tools")],
)
async def test_background_policy_uses_actual_model_after_budget_fallback(
    monkeypatch, respx_mock, anthropic_client, purpose, model, mode
):
    monkeypatch.setattr(llm, "_client", anthropic_client)
    monkeypatch.setattr(budget, "model_for", AsyncMock(return_value=model))
    record = AsyncMock()
    monkeypatch.setattr(usage, "record", record)
    route = respx_mock.post("https://api.anthropic.com/v1/messages").respond(
        200,
        json={
            "id": "background-test",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [{"type": "text", "text": "Sažetak."}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 50, "output_tokens": 10},
        },
    )
    await llm.create(
        purpose=purpose,
        model="claude-opus-5-5",
        max_tokens=400,
        messages=[{"role": "user", "content": "Podaci"}],
    )
    body = json.loads(route.calls[0].request.content)
    assert body["model"] == model
    assert body["thinking"] == {"type": mode}
    assert body["output_config"] == {"effort": "low"}
    record.assert_awaited_once()
    assert record.call_args.args[1] == purpose


@pytest.mark.parametrize(
    "purpose,extra",
    [
        ("chat", {}),
        ("scheduler", {"model": "claude-haiku-4-5"}),
        ("scheduler", {"model": "claude-opus-5-5"}),
        ("scheduler", {"thinking": {"type": "adaptive"}}),
        ("scheduler", {"output_config": {"effort": "max"}}),
        ("scheduler", {"tools": [{"name": "neki_alat"}]}),
    ],
)
def test_policy_leaves_chat_other_models_and_explicit_options_unchanged(purpose, extra):
    original = {"model": "claude-haiku-5-5", "max_tokens": 400, **extra}
    assert llm.background_options(purpose, original) is original


async def test_truncation_retries_once_and_accounts_for_both_sdk_responses(
    monkeypatch, respx_mock, anthropic_client, caplog
):
    import httpx

    monkeypatch.setattr(llm, "_client", anthropic_client)
    monkeypatch.setattr(budget, "model_for", AsyncMock(return_value="claude-haiku-5-5"))
    record = AsyncMock()
    monkeypatch.setattr(usage, "record", record)
    results = iter(
        [
            ([{"type": "thinking", "thinking": "", "signature": "private"}], "max_tokens"),
            ([{"type": "text", "text": "Gotov sažetak."}], "end_turn"),
        ]
    )

    def reply(request):
        content, stop = next(results)
        return httpx.Response(
            200,
            json={
                "id": "retry-test",
                "type": "message",
                "role": "assistant",
                "model": "claude-haiku-5-5",
                "content": content,
                "stop_reason": stop,
                "usage": {"input_tokens": 80, "output_tokens": 400},
            },
        )

    route = respx_mock.post("https://api.anthropic.com/v1/messages").mock(side_effect=reply)
    text = await llm.create_text(
        purpose="scheduler",
        model="claude-haiku-5-5",
        max_tokens=400,
        retry_tokens=800,
        max_chars=1200,
        messages=[{"role": "user", "content": "PRIVATNI_PODACI"}],
    )
    assert text == "Gotov sažetak."
    assert [json.loads(c.request.content)["max_tokens"] for c in route.calls] == [400, 800]
    assert record.await_count == 2
    assert "prekid=max_tokens" in caplog.text and "znakova=0" in caplog.text
    assert "PRIVATNI_PODACI" not in caplog.text and "signature" not in caplog.text


@pytest.mark.parametrize(
    "text,stop,count",
    [
        ("Prekinuto", "max_tokens", 2),
        ("", "end_turn", 1),
        ("Odbijeno", "refusal", 1),
        ("X" * 101, "end_turn", 1),
    ],
)
async def test_invalid_text_is_never_returned_and_refusal_is_not_retried(
    monkeypatch, text, stop, count
):
    create = AsyncMock(return_value=response(text, stop))
    monkeypatch.setattr(llm, "create", create)
    with pytest.raises(llm.IncompleteText):
        await llm.create_text(
            purpose="scheduler", max_tokens=400, retry_tokens=800, max_chars=100, model="test"
        )
    assert create.await_count == count


async def test_api_error_does_not_trigger_extra_text_attempt(monkeypatch):
    create = AsyncMock(side_effect=RuntimeError("API greška"))
    monkeypatch.setattr(llm, "create", create)
    with pytest.raises(RuntimeError, match="API greška"):
        await llm.create_text(
            purpose="scheduler", max_tokens=400, retry_tokens=800, max_chars=100, model="test"
        )
    create.assert_awaited_once()

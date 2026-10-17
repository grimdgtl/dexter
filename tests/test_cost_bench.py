from pathlib import Path

from apu import llm, usage
from apu.config import settings
from evals.cost_bench import read_prompts


def test_cache_off_removes_nested_markers_without_changing_original(monkeypatch):
    original = {
        "system": [{"text": "Statično", "cache_control": {"type": "ephemeral"}}],
        "messages": [{"content": [{"type": "text", "text": "Poruka", "cache_control": {}}]}],
    }
    monkeypatch.setattr(settings(), "prompt_cache", "off")
    assert "cache_control" not in str(llm.request_options(original))
    assert "cache_control" in str(original)


def test_fixed_benchmark_has_fifty_public_prompts():
    assert len(read_prompts(Path("evals/prompts.jsonl"))) == 50


def test_usage_capture_is_scoped():
    with usage.capture() as rows:
        assert usage._capture.get() is rows
    assert usage._capture.get() is None


async def test_benchmark_rejects_main_database_before_connecting(monkeypatch):
    from unittest.mock import AsyncMock

    import pytest

    from evals import cost_bench

    monkeypatch.setattr(settings(), "database_url", "postgresql://test@localhost/apu")
    connect = AsyncMock()
    monkeypatch.setattr(cost_bench.db, "connect", connect)
    with pytest.raises(ValueError, match="izdvojenu"):
        await cost_bench.main(simulation=True)
    connect.assert_not_awaited()

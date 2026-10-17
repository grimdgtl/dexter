from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from apu.agent import router
from apu.config import settings


@pytest.mark.parametrize("level,tier", [("lako", "fast"), ("srednje", "main"), ("teško", "deep")])
async def test_classifier_selects_tier(monkeypatch, level, tier):
    monkeypatch.setattr(settings(), "router_mode", "classifier")
    create = AsyncMock(
        return_value=SimpleNamespace(
            content=[SimpleNamespace(type="text", text='{"nivo":"' + level + '"}')],
            stop_reason="end_turn",
        )
    )
    monkeypatch.setattr(router.llm, "create", create)
    assert (await router.select_model("Poruka"))[0] == getattr(settings(), "model_" + tier)
    assert create.await_args.kwargs["purpose"] == "router"


@pytest.mark.parametrize("bad", ["nije json", '{"nivo":"nepoznato"}', '{"nivo":[]}', "{}"])
async def test_classifier_failure_falls_back_to_rule(monkeypatch, bad):
    monkeypatch.setattr(settings(), "router_mode", "classifier")
    monkeypatch.setattr(
        router.llm,
        "create",
        AsyncMock(
            return_value=SimpleNamespace(
                content=[SimpleNamespace(type="text", text=bad)], stop_reason="end_turn"
            )
        ),
    )
    assert await router.select_model("Poruka") == router.pick_model("Poruka")


async def test_explicit_deep_prefix_bypasses_classifier(monkeypatch):
    monkeypatch.setattr(settings(), "router_mode", "classifier")
    create = AsyncMock()
    monkeypatch.setattr(router.llm, "create", create)
    assert await router.select_model("/duboko Analiziraj") == (settings().model_deep, "Analiziraj")
    create.assert_not_awaited()

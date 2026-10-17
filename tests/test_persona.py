import json
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from apu.agent.prompts import SYSTEM_PROMPT
from apu.config import settings
from apu.tools import registry
from evals import persona_eval, persona_gate
from evals.persona_support import HERE, corpus_hash, digest, prompt_from_source, read_cases


def test_public_persona_corpus_and_judge_scores_are_complete():
    rows = read_cases()
    assert len(rows) == len({r["id"] for r in rows}) == 20
    with pytest.raises(ValidationError):
        persona_eval.Judgment.model_validate(
            {
                "ocene": {k: 6 for k in persona_eval.Scores.model_fields},
                "obrazlozenje": "Loša ocena",
            }
        )
    with pytest.raises(ValueError, match="statična"):
        prompt_from_source("SYSTEM_PROMPT = build_prompt()")
    assert registry._TOOLS["memory_forget"].confirm


def test_gate_rejects_simulation_and_mismatched_corpus():
    rows = read_cases()
    rubric = json.loads((HERE / "rubric.json").read_text())
    cases = [
        {
            "id": r["id"],
            "ocene": {k: 4 for k in persona_eval.Scores.model_fields},
            "obrazlozenje": "Kontrola validacije.",
        }
        for r in rows
    ]
    report = {
        "simulacija": False,
        "skup_sha256": corpus_hash(rows),
        "rubrika_sha256": corpus_hash(rubric),
        "kandidat": "kontrolni kandidat",
        "sudija": "kontrolni sudija",
        "pre": {"prompt_sha256": digest("stari"), "n": 20, "slučajevi": cases},
        "posle": {"prompt_sha256": digest("novi"), "n": 20, "slučajevi": cases},
    }
    assert persona_gate.verify_report(report, "stari", "novi", rows, rubric)
    assert not persona_gate.verify_report(
        {**report, "simulacija": True}, "stari", "novi", rows, rubric
    )
    assert not persona_gate.verify_report(
        {**report, "skup_sha256": "drugi"}, "stari", "novi", rows, rubric
    )


async def test_gate_requires_measurement_only_when_prompt_changes(monkeypatch, tmp_path):
    monkeypatch.setattr(persona_gate, "git_prompt", AsyncMock(return_value=SYSTEM_PROMPT))
    assert await persona_gate.check(directory=tmp_path)
    monkeypatch.setattr(persona_gate, "git_prompt", AsyncMock(return_value="stari"))
    with pytest.raises(ValueError, match="stvarnog persona"):
        await persona_gate.check(directory=tmp_path)


async def test_persona_refuses_production_database_before_connecting(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(settings(), "database_url", "postgresql://localhost/apu")
    connect = AsyncMock()
    monkeypatch.setattr(persona_eval.db, "connect", connect)
    with pytest.raises(ValueError, match="izdvojenu"):
        await persona_eval.main(SimpleNamespace(simulacija=True))
    connect.assert_not_awaited()

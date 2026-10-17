from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from apu import proactive
from apu.config import settings


@pytest.mark.parametrize(
    "data",
    [
        {"posalji": "false", "poruka": "", "razlog": "Nema"},
        {"posalji": True, "poruka": "  ", "razlog": "Nema"},
        {"posalji": True, "poruka": "a" * 3501, "razlog": "Nema"},
    ],
)
def test_decision_requires_strict_complete_json(data):
    with pytest.raises(ValidationError):
        proactive.Decision.model_validate(data)


async def test_collect_marks_missing_sources_without_inventing_empty_state(monkeypatch):
    monkeypatch.setattr(proactive.google, "configured", lambda: False)
    monkeypatch.setattr(proactive.mail, "configured", lambda: False)
    monkeypatch.setattr(settings(), "notion_tasks_db_id", None)
    monkeypatch.setattr(proactive.commitments, "list_all", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        proactive.memory, "recall", AsyncMock(side_effect=RuntimeError("tajna veza"))
    )
    data = await proactive.collect(
        datetime(2026, 10, 17, 8, 30, tzinfo=ZoneInfo("Europe/Belgrade"))
    )
    assert data["kalendar"]["status"] == "isključeno"
    assert data["činjenice"]["status"] == "greška"
    assert "tajna" not in str(data)

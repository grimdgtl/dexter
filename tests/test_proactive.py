from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from dexter import proactive
from dexter.config import settings


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


def test_weekly_scheduler_is_sunday_at_twenty_and_preserves_other_jobs(monkeypatch):
    from dexter import scheduler

    monkeypatch.setattr(scheduler.AsyncIOScheduler, "start", lambda self: None)
    schedule = scheduler.start(SimpleNamespace())
    now = datetime(2026, 10, 17, 12, tzinfo=ZoneInfo("Europe/Belgrade"))
    fire = schedule.get_job("weekly_review").trigger.get_next_fire_time(None, now)
    assert fire.weekday() == 6 and (fire.hour, fire.minute) == (20, 0)
    assert schedule.get_job("daily_insight") and schedule.get_job("morning")

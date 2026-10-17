from datetime import UTC, date, datetime
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from apu.rag.dates import period_bounds, timestamp
from apu.rag.store import Hit
from apu.tools.knowledge import SearchArgs, knowledge_search


def test_local_period_has_inclusive_days_and_handles_dst():
    lower, upper = period_bounds(date(2026, 10, 25), date(2026, 10, 25))
    assert (upper.astimezone(UTC) - lower.astimezone(UTC)).total_seconds() == 25 * 3600
    assert lower.isoformat() == "2026-10-25T00:00:00+02:00"
    assert upper.isoformat() == "2026-10-26T00:00:00+01:00"
    assert period_bounds(None, None) == (None, None)
    assert timestamp(None) is None
    assert timestamp("2026-09-01T00:00:00Z") == datetime(2026, 9, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="vremensku zonu"):
        timestamp(datetime(2026, 9, 1))


@pytest.mark.parametrize(
    "start,end", [("2026-10-01", "2026-09-01"), (None, "9999-12-31"), ("nije datum", None)]
)
def test_invalid_period_is_rejected_before_search(start, end):
    with pytest.raises(ValidationError):
        SearchArgs(upit="Orion", od=start, do=end)


async def test_knowledge_tool_forwards_dates_and_reports_source_timestamp(monkeypatch):
    from apu.tools import knowledge

    search = AsyncMock(
        return_value=[
            Hit(
                1,
                "doc:1",
                "Naslov",
                None,
                "Tekst",
                0.02,
                modified_at=datetime(2026, 9, 1, tzinfo=UTC),
            )
        ]
    )
    monkeypatch.setattr(knowledge.store, "search", search)
    args = SearchArgs(upit="Orion", izvor="razgovor", od="2026-09-01", do="2026-09-30")
    result = await knowledge_search(args)
    search.assert_awaited_once_with(
        "Orion", limit=6, source="razgovor", date_from=date(2026, 9, 1), date_to=date(2026, 9, 30)
    )
    assert result["rezultati"][0]["datum"] == "2026-09-01T02:00:00+02:00"

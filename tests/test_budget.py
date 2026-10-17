from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from apu import budget
from apu.config import Settings, settings


@pytest.mark.parametrize("value", [0, -1, "NaN", "Infinity"])
def test_budget_rejects_invalid_amount(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, daily_budget_usd=value)


async def test_database_failure_uses_fast_model(monkeypatch):
    monkeypatch.setattr(settings(), "daily_budget_usd", Decimal("1"))
    monkeypatch.setattr(budget, "snapshot", AsyncMock(side_effect=RuntimeError("Baza")))
    assert await budget.model_for(settings().model_deep) == settings().model_fast

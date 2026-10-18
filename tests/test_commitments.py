from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from dexter import commitments
from dexter.config import settings
from dexter.proactive_time import quiet


@pytest.mark.parametrize(
    "hour,expected", [(21, False), (22, True), (0, True), (6, True), (7, False)]
)
def test_quiet_hours_cross_midnight(monkeypatch, hour, expected):
    monkeypatch.setattr(settings(), "quiet_hours", "22-07")
    assert quiet(datetime(2026, 10, 17, hour, tzinfo=ZoneInfo("Europe/Belgrade"))) is expected


def test_blank_proof_and_invalid_deadline_are_rejected():
    for changes in ({"dokaz": "     "}, {"rok": "2026-02-30"}):
        with pytest.raises(ValidationError):
            commitments.Commitment.model_validate(
                {
                    "tekst": "Poslati ponudu",
                    "rok": "2026-10-23",
                    "dokaz": "Poslaću ponudu do petka",
                    **changes,
                }
            )

"""Datumi izvora i uključivi lokalni dani, nezavisno od vremena indeksiranja."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from apu.config import settings


def timestamp(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    except ValueError as exc:
        raise ValueError("Datum izvora nije ispravan ISO datum.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Datum izvora mora imati vremensku zonu.")
    return parsed


def day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, ZoneInfo(settings().timezone))


def period_bounds(start: date | None, end: date | None) -> tuple[datetime | None, datetime | None]:
    if start and end and start > end:
        raise ValueError("Datum od mora biti pre ili jednak datumu do.")
    if end == date.max:
        raise ValueError("Datum do mora biti pre 9999-12-31.")
    return day_start(start) if start else None, day_start(end + timedelta(days=1)) if end else None

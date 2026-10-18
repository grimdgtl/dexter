"""Lokalni kalendarski dan određuje rokove i tihe sate, ne UTC datum servera."""

from datetime import datetime
from zoneinfo import ZoneInfo

from dexter.config import settings


def local_now(now: datetime | None = None) -> datetime:
    if now is not None and now.tzinfo is None:
        raise ValueError("Vreme mora imati vremensku zonu.")
    return (now or datetime.now(ZoneInfo(settings().timezone))).astimezone(
        ZoneInfo(settings().timezone)
    )


def quiet(now: datetime | None = None) -> bool:
    start, end = map(int, settings().quiet_hours.split("-"))
    hour = local_now(now).hour
    return (hour >= start or hour < end) if start >= end else start <= hour < end

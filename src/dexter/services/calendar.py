"""Google Calendar kroz zajednički OAuth; svaki SDK klijent pripada jednoj operaciji."""

import asyncio
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from dexter.config import settings
from dexter.pismo import u_latinicu
from dexter.services import google


def parse_time(value: str) -> datetime:
    try:
        if len(value) == 10:
            return datetime.combine(
                date.fromisoformat(value), time.min, ZoneInfo(settings().timezone)
            )
        stamp = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Koristi ISO datum ili datum/vreme sa vremenskom zonom.") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("Datum/vreme mora imati vremensku zonu.")
    return stamp


def window(time_min: str | None = None, time_max: str | None = None):
    start = parse_time(time_min) if time_min else datetime.now(ZoneInfo(settings().timezone))
    end = parse_time(time_max) if time_max else start + timedelta(days=7)
    if start >= end:
        raise ValueError("Kraj opsega mora biti posle početka.")
    return start, end


class Calendar:
    async def __aenter__(self):
        self.api = await asyncio.to_thread(google.build_service, "calendar", "v3")
        return self

    async def __aexit__(self, *args):
        await asyncio.to_thread(self.api.close)

    async def call(self, resource: str, method: str, **kwargs):
        def execute():
            return getattr(getattr(self.api, resource)(), method)(**kwargs).execute()

        return await asyncio.to_thread(execute)


async def raw_events(start: datetime, end: datetime) -> list[dict]:
    async with Calendar() as api:
        rows, seen, cursor = [], set(), None
        while True:
            data = await api.call(
                "events",
                "list",
                calendarId=settings().google_calendar_id,
                timeMin=start.isoformat(),
                timeMax=end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=250,
                pageToken=cursor,
            )
            rows.extend(e for e in data.get("items", []) if e.get("status") != "cancelled")
            cursor = data.get("nextPageToken")
            if not cursor:
                return rows
            if cursor in seen:
                raise ValueError("Kalendar je ponovio token paginacije.")
            seen.add(cursor)


def event_data(event: dict) -> dict:
    return {
        "id": event["id"],
        "summary": u_latinicu(event.get("summary", "(bez naslova)")),
        "start": event.get("start", {}).get("dateTime") or event.get("start", {}).get("date"),
        "end": event.get("end", {}).get("dateTime") or event.get("end", {}).get("date"),
        "location": u_latinicu(event["location"]) if event.get("location") else None,
        "attendees": [a["email"] for a in event.get("attendees", []) if a.get("email")],
        "htmlLink": event.get("htmlLink"),
    }


async def list_events(time_min: str | None = None, time_max: str | None = None) -> list[dict]:
    return [event_data(e) for e in await raw_events(*window(time_min, time_max))]


async def find_free_slots(
    time_min: str | None = None,
    time_max: str | None = None,
    duration_minutes: int = 60,
    workday_start: int = 9,
    workday_end: int = 18,
) -> list[dict]:
    start, end = window(time_min, time_max)
    tz = ZoneInfo(settings().timezone)
    calendar_id = settings().google_calendar_id
    async with Calendar() as api:
        data = await api.call(
            "freebusy",
            "query",
            body={
                "timeMin": start.isoformat(),
                "timeMax": end.isoformat(),
                "timeZone": settings().timezone,
                "items": [{"id": calendar_id}],
            },
        )
    entry = data.get("calendars", {}).get(calendar_id)
    # Nepoznata zauzetost ne sme da postane preporuka slobodnog termina.
    if not isinstance(entry, dict) or entry.get("errors") or "busy" not in entry:
        raise ValueError("Google nije potvrdio zauzetost izabranog kalendara.")
    busy = sorted(
        (parse_time(b["start"]).astimezone(UTC), parse_time(b["end"]).astimezone(UTC))
        for b in entry["busy"]
    )
    if any(a >= b for a, b in busy):
        raise ValueError("Google je vratio neispravan interval zauzetosti.")
    minimum = max(start.astimezone(UTC), datetime.now(UTC))
    maximum = end.astimezone(UTC)
    day = minimum.astimezone(tz).date()
    slots = []
    while day <= end.astimezone(tz).date() and minimum < maximum:
        lower = datetime.combine(day, time(workday_start), tz).astimezone(UTC)
        upper = (
            datetime.combine(day + timedelta(days=1), time.min, tz)
            if workday_end == 24
            else datetime.combine(day, time(workday_end), tz)
        ).astimezone(UTC)
        cursor, stop = max(lower, minimum), min(upper, maximum)
        for begin, finish in busy:
            if finish <= cursor or begin >= stop:
                continue
            if min(begin, stop) - cursor >= timedelta(minutes=duration_minutes):
                slots.append(
                    {
                        "start": cursor.astimezone(tz).isoformat(),
                        "end": begin.astimezone(tz).isoformat(),
                    }
                )
            cursor = max(cursor, finish)
        if stop - cursor >= timedelta(minutes=duration_minutes):
            slots.append(
                {"start": cursor.astimezone(tz).isoformat(), "end": stop.astimezone(tz).isoformat()}
            )
        day += timedelta(days=1)
    return slots


async def create_event(
    summary: str,
    start: datetime,
    end: datetime,
    location: str | None = None,
    description: str | None = None,
    attendees: list[str] | None = None,
    recurrence: str | None = None,
) -> dict:
    tz = ZoneInfo(settings().timezone)
    guests = attendees or []
    body = {
        "summary": u_latinicu(summary),
        "start": {"dateTime": start.astimezone(tz).isoformat(), "timeZone": settings().timezone},
        "end": {"dateTime": end.astimezone(tz).isoformat(), "timeZone": settings().timezone},
        "attendees": [{"email": email} for email in guests],
        "reminders": {"useDefault": True},
    }
    if location is not None:
        body["location"] = u_latinicu(location)
    if description is not None:
        body["description"] = u_latinicu(description)
    if recurrence:
        body["recurrence"] = [recurrence]
    async with Calendar() as api:
        event = await api.call(
            "events",
            "insert",
            calendarId=settings().google_calendar_id,
            body=body,
            sendUpdates="all" if guests else "none",
        )
    return {**event_data(event), "ponavljanje": (event.get("recurrence") or [None])[0]}

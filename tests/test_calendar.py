"""Pravi Google SDK sa respx transportom; aktivni kalendar se ne poziva u testovima."""

import json
import threading
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx
import pytest
from googleapiclient.errors import HttpError
from pydantic import ValidationError

from dexter import config
from dexter.services import calendar, google
from dexter.tools import calendar as tools
from dexter.tools import registry

BASE = "https://www.googleapis.com/calendar/v3"


@pytest.fixture(autouse=True)
def calendar_config(monkeypatch):
    for name in google.REQUIRES:
        monkeypatch.setenv(name, "test")
    monkeypatch.setenv("GOOGLE_CALENDAR_ID", "primary")
    monkeypatch.setenv("TIMEZONE", "Europe/Belgrade")
    config.settings.cache_clear()

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 18, 8, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(calendar, "datetime", Clock)
    yield
    config.settings.cache_clear()


@pytest.fixture
def token(respx_mock):
    return respx_mock.post("https://oauth2.googleapis.com/token").respond(
        200, json={"access_token": "access-test", "expires_in": 3600, "token_type": "Bearer"}
    )


async def test_list_paginates_all_pages_and_preserves_all_day_events(respx_mock, token):
    owner = threading.get_ident()

    def page(request):
        assert threading.get_ident() != owner
        assert request.headers["authorization"] == "Bearer access-test"
        if request.url.params.get("pageToken"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"id": "2", "start": {"date": "2026-10-20"}, "end": {"date": "2026-10-21"}}
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "nextPageToken": "jos",
                "items": [
                    {
                        "id": "1",
                        "summary": "Састанак",
                        "start": {"dateTime": "2026-10-19T09:00:00+02:00"},
                        "end": {"dateTime": "2026-10-19T10:00:00+02:00"},
                        "location": "Канцеларија",
                        "attendees": [{"email": "marko@example.com"}],
                        "htmlLink": "https://calendar.google.com/1",
                    },
                    {"id": "obrisan", "status": "cancelled"},
                ],
            },
        )

    route = respx_mock.get(f"{BASE}/calendars/primary/events").mock(side_effect=page)
    rows = await tools.calendar_list_events(tools.RangeArgs())
    assert [e["id"] for e in rows] == ["1", "2"]
    assert rows[0]["summary"] == "Sastanak" and rows[0]["location"] == "Kancelarija"
    assert rows[0]["attendees"] == ["marko@example.com"]
    assert rows[1]["start"] == "2026-10-20" and rows[1]["end"] == "2026-10-21"
    assert token.call_count == 1 and route.call_count == 2
    query = route.calls[0].request.url.params
    assert query["singleEvents"] == "true" and query["orderBy"] == "startTime"
    assert query["timeMin"] == "2026-10-18T10:00:00+02:00"
    assert query["timeMax"] == "2026-10-25T10:00:00+01:00"


async def test_list_rejects_repeated_cursor_and_closes_sdk(respx_mock, token, monkeypatch):
    closed = []
    build = google.build_service

    def tracked(*args):
        api = build(*args)
        close = api.close

        def tracked_close():
            closed.append(True)
            close()

        api.close = tracked_close
        return api

    monkeypatch.setattr(google, "build_service", tracked)
    respx_mock.get(f"{BASE}/calendars/primary/events").respond(
        200, json={"items": [], "nextPageToken": "isto"}
    )
    with pytest.raises(ValueError, match="ponovio"):
        await calendar.list_events()
    assert closed == [True]


@pytest.mark.parametrize("operation", ["list", "freebusy", "create"])
async def test_permission_errors_are_not_empty_results(respx_mock, token, operation):
    if operation == "list":
        route = respx_mock.get(f"{BASE}/calendars/primary/events")
        call = calendar.list_events()
    elif operation == "freebusy":
        route = respx_mock.post(f"{BASE}/freeBusy")
        call = calendar.find_free_slots()
    else:
        route = respx_mock.post(f"{BASE}/calendars/primary/events")
        call = tools.calendar_create_event(
            tools.CreateArgs(
                summary="Proba", start="2026-10-19T10:00:00+02:00", end="2026-10-19T11:00:00+02:00"
            )
        )
    route.respond(403, json={"error": {"code": 403, "message": "Nema pristupa"}})
    with pytest.raises(HttpError):
        await call


def busy_response(respx_mock, periods):
    return respx_mock.post(f"{BASE}/freeBusy").respond(
        200, json={"calendars": {"primary": {"busy": [{"start": a, "end": b} for a, b in periods]}}}
    )


async def test_free_slots_merge_overlaps_and_clip_to_query_and_now(respx_mock, token):
    route = busy_response(
        respx_mock,
        [
            ("2026-10-18T12:00:00+02:00", "2026-10-18T14:00:00+02:00"),
            ("2026-10-18T11:30:00+02:00", "2026-10-18T13:00:00+02:00"),
            ("2026-10-18T09:30:00+02:00", "2026-10-18T10:30:00+02:00"),
        ],
    )
    rows = await tools.calendar_find_free_slots(
        tools.FreeArgs(timeMin="2026-10-18T09:00:00+02:00", timeMax="2026-10-18T15:00:00+02:00")
    )
    assert rows == [
        {"start": "2026-10-18T10:30:00+02:00", "end": "2026-10-18T11:30:00+02:00"},
        {"start": "2026-10-18T14:00:00+02:00", "end": "2026-10-18T15:00:00+02:00"},
    ]
    body = json.loads(route.calls[0].request.content)
    assert body["items"] == [{"id": "primary"}] and body["timeZone"] == "Europe/Belgrade"


async def test_free_slots_cover_empty_calendar_and_dst_weekend(respx_mock, token):
    busy_response(respx_mock, [])
    rows = await calendar.find_free_slots("2026-10-24", "2026-10-26")
    assert rows == [
        {"start": "2026-10-24T09:00:00+02:00", "end": "2026-10-24T18:00:00+02:00"},
        {"start": "2026-10-25T09:00:00+01:00", "end": "2026-10-25T18:00:00+01:00"},
    ]
    assert await calendar.find_free_slots("2026-10-17", "2026-10-18") == []


@pytest.mark.parametrize("entry", [{}, {"errors": [{"reason": "notFound"}]}, None])
async def test_unknown_availability_never_becomes_a_free_slot(respx_mock, token, entry):
    respx_mock.post(f"{BASE}/freeBusy").respond(200, json={"calendars": {"primary": entry}})
    with pytest.raises(ValueError, match="nije potvrdio"):
        await calendar.find_free_slots()


@pytest.mark.parametrize("attendees,updates", [([], "none"), (["marko@example.com"], "all")])
async def test_single_recurring_insert_waits_for_confirmation(
    respx_mock, token, monkeypatch, attendees, updates
):
    monkeypatch.setattr(registry, "_PENDING", {})
    owner = threading.get_ident()

    def insert(request):
        assert threading.get_ident() != owner
        assert request.url.params["sendUpdates"] == updates
        body = json.loads(request.content)
        assert body["summary"] == "Proba" and body["reminders"] == {"useDefault": True}
        assert body["recurrence"] == [
            "RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=WE;UNTIL=20261231T235959Z"
        ]
        assert body["start"] == {
            "dateTime": "2026-10-21T12:00:00+02:00",
            "timeZone": "Europe/Belgrade",
        }
        return httpx.Response(
            200, json={**body, "id": "novo", "htmlLink": "https://calendar.google.com/novo"}
        )

    route = respx_mock.post(f"{BASE}/calendars/primary/events").mock(side_effect=insert)
    args = {
        "summary": "Проба",
        "start": "2026-10-21T10:00:00Z",
        "end": "2026-10-21T11:00:00Z",
        "location": "Канцеларија",
        "description": "Провера",
        "attendees": attendees,
        "ponavljanje": {"ucestalost": "WEEKLY", "interval": 2, "dani": ["WE"], "do": "2026-12-31"},
    }
    outcome = await registry.execute("calendar_create_event", args)
    assert outcome.pending and route.call_count == 0 and token.call_count == 0
    key, preview = outcome.pending
    assert "Proba" in preview and "12:00" in preview and "primary" in preview
    assert "Pozivnice:" in preview and (not attendees or attendees[0] in preview)
    result = json.loads(await registry.confirm(key))
    assert result["id"] == "novo" and result["ponavljanje"].startswith("RRULE:")
    assert result["location"] == "Kancelarija" and route.call_count == 1
    assert "već obrađena" in await registry.confirm(key)
    assert route.call_count == 1


async def test_cancelled_event_never_calls_google(monkeypatch):
    monkeypatch.setattr(registry, "_PENDING", {})
    create = AsyncMock()
    monkeypatch.setattr(calendar, "create_event", create)
    outcome = await registry.execute(
        "calendar_create_event",
        {
            "summary": "Proba",
            "start": "2026-10-19T10:00:00+02:00",
            "end": "2026-10-19T11:00:00+02:00",
        },
    )
    registry.cancel(outcome.pending[0])
    await registry.confirm(outcome.pending[0])
    create.assert_not_awaited()


async def test_single_event_uses_configured_calendar_and_winter_timezone(
    respx_mock, token, monkeypatch
):
    monkeypatch.setattr(config.settings(), "google_calendar_id", "privatni")
    route = respx_mock.post(f"{BASE}/calendars/privatni/events")
    route.respond(
        200,
        json={
            "id": "jedan",
            "summary": "Proba",
            "start": {"dateTime": "2026-10-26T10:00:00+01:00"},
            "end": {"dateTime": "2026-10-26T11:00:00+01:00"},
        },
    )
    result = await tools.calendar_create_event(
        tools.CreateArgs(summary="Proba", start="2026-10-26T09:00:00Z", end="2026-10-26T10:00:00Z")
    )
    body = json.loads(route.calls[0].request.content)
    assert "recurrence" not in body and "location" not in body
    assert body["start"]["dateTime"] == "2026-10-26T10:00:00+01:00"
    assert result["ponavljanje"] is None and result["id"] == "jedan"


def test_rrule_count_and_validation():
    assert tools.RepeatArgs(ucestalost="daily", broj=3).rrule() == "RRULE:FREQ=DAILY;COUNT=3"
    for values in [
        {"ucestalost": "WEEKLY", "do": "2026-12-31", "broj": 2},
        {"ucestalost": "WEEKLY", "dani": ["XX"]},
        {"ucestalost": "WEEKLY", "interval": 0},
    ]:
        with pytest.raises(ValidationError):
            tools.RepeatArgs(**values)


@pytest.mark.parametrize(
    "data",
    [
        {"timeMin": "2026-10-19T12:00:00"},
        {"timeMin": "2026-10-20", "timeMax": "2026-10-19"},
        {"durationMinutes": 0},
        {"workdayStart": 18, "workdayEnd": 9},
    ],
)
def test_invalid_free_slot_arguments(data):
    with pytest.raises(ValidationError):
        tools.FreeArgs(**data)


def test_invalid_events_and_missing_config_are_rejected(monkeypatch):
    event = {
        "summary": "Proba",
        "start": "2026-10-21T12:00:00+02:00",
        "end": "2026-10-21T13:00:00+02:00",
    }
    for change in [
        {"summary": "  "},
        {"start": "2026-10-21T12:00:00"},
        {"end": event["start"]},
        {"attendees": ["nije-email"]},
        {"ponavljanje": {"ucestalost": "WEEKLY", "do": "2026-10-20"}},
    ]:
        with pytest.raises(ValidationError):
            tools.CreateArgs(**{**event, **change})
    monkeypatch.setattr(config.settings(), "google_refresh_token", None)
    for name in ("calendar_list_events", "calendar_find_free_slots", "calendar_create_event"):
        assert "GOOGLE_REFRESH_TOKEN" in registry._TOOLS[name].disabled_reason()

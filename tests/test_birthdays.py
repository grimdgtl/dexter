import json
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from dexter.config import settings
from dexter.proactive_time import local_now
from dexter.services import birthdays
from dexter.tools import registry


@pytest.fixture
def birthday_notion(monkeypatch, respx_mock):
    base = "https://api.notion.com/v1"
    database, source = str(uuid4()), str(uuid4())
    monkeypatch.setattr(settings(), "notion_api_key", "test-notion")
    monkeypatch.setattr(settings(), "notion_birthdays_db_id", database)
    monkeypatch.setattr(settings(), "timezone", "Europe/Belgrade")
    monkeypatch.setattr(birthdays, "today", lambda: date(2026, 10, 18))
    respx_mock.get(f"{base}/databases/{database}").respond(
        200, json={"data_sources": [{"id": source}]}
    )
    pages = []

    def add(name="Марко", born="1990-10-18", **extra):
        page = {
            "id": str(uuid4()),
            "url": "https://notion.so/birthday",
            "properties": {
                "Ime i prezime": {"type": "title", "title": [{"plain_text": name}]},
                "Rođendan": {"date": {"start": born} if born else None},
                "Odnos": {"select": {"name": "Пријатељ"}},
                "Telefon": {"phone_number": "+381600000000"},
                "Ideja za poklon": {"rich_text": [{"plain_text": "Књига"}]},
                "Napomena": {"rich_text": [{"plain_text": "Проба"}]},
            },
            **extra,
        }
        pages.append(page)
        return page

    query = respx_mock.post(f"{base}/data_sources/{source}/query").mock(
        side_effect=lambda request: httpx.Response(200, json={"results": pages, "has_more": False})
    )
    return SimpleNamespace(
        base=base, database=database, source=source, pages=pages, add=add, query=query
    )


async def test_birthdays_today_keeps_v1_fields_and_latin(birthday_notion):
    n = birthday_notion
    first = n.add()
    n.add("Sutra", "1999-10-19")
    n.add("Bez datuma", None)
    n.add("Arhiviran", archived=True)
    out = await registry.execute("birthdays_today", {})
    assert not out.is_error
    rows = json.loads(out.text)
    assert len(rows) == 1
    assert rows[0] == {
        "id": first["id"],
        "url": first["url"],
        "name": "Marko",
        "date": "1990-10-18",
        "relation": "Prijatelj",
        "phone": "+381600000000",
        "giftIdea": "Knjiga",
        "note": "Proba",
        "age": 36,
    }


@pytest.mark.parametrize("year,day", [(2026, 28), (2028, 29), (2100, 28), (2000, 29)])
def test_leap_anniversary(year, day):
    assert birthdays.anniversary(date(2000, 2, 29), year) == date(year, 2, day)


@pytest.mark.parametrize(
    "birth_year,expected", [(2026, None), (2027, None), (1906, None), (1907, 119), (1990, 36)]
)
def test_age_is_not_invented(birth_year, expected):
    assert birthdays.age_turning(date(birth_year, 1, 1), 2026) == expected


async def test_upcoming_uses_leap_rule_inclusive_limit_and_new_year(birthday_notion, monkeypatch):
    n = birthday_notion
    n.add("Prestupni", "2000-02-29")
    n.add("Mart", "1999-03-01")
    monkeypatch.setattr(birthdays, "today", lambda: date(2026, 2, 28))
    out = await birthdays.upcoming(0)
    assert [(r["name"], r["inDays"], r["age"]) for r in out] == [("Prestupni", 0, 26)]
    n.pages.clear()
    n.add("Nova godina", "2000-01-01")
    n.add("Danas", "2000-12-31")
    monkeypatch.setattr(birthdays, "today", lambda: date(2026, 12, 31))
    out = await birthdays.upcoming(1)
    assert [(r["name"], r["inDays"], r["age"]) for r in out] == [
        ("Danas", 0, 26),
        ("Nova godina", 1, 27),
    ]


def test_local_day_crosses_utc_midnight(monkeypatch):
    monkeypatch.setattr(settings(), "timezone", "Europe/Belgrade")
    monkeypatch.setattr(
        birthdays, "local_now", lambda: local_now(datetime(2026, 10, 17, 22, 30, tzinfo=UTC))
    )
    assert birthdays.today() == date(2026, 10, 18)


async def test_birthdays_paginates_and_weekday_names(birthday_notion):
    n = birthday_notion
    first = n.add("Danas")
    second = n.add("Utorak", "1990-10-20")
    n.query.mock(
        side_effect=[
            httpx.Response(
                200, json={"results": [first], "has_more": True, "next_cursor": "druga"}
            ),
            httpx.Response(200, json={"results": [second], "has_more": False}),
        ]
    )
    rows = await birthdays.this_week()
    assert [(r["dayName"], r["dayDate"]) for r in rows] == [
        ("nedelja", "18.10."),
        ("utorak", "20.10."),
    ]
    assert json.loads(n.query.calls[1].request.content)["start_cursor"] == "druga"


@pytest.mark.parametrize(
    "name,names,matched,ambiguous",
    [
        ("", ["Marko"], "Marko", False),
        ("Марко", ["Marko", "Marko Marković"], "Marko", False),
        ("Marko", ["Marko Petrović", "Marko Marković"], None, True),
        ("Petrović", ["Marko Petrović", "Jovan"], "Marko Petrović", False),
        ("Jovan", ["Marko"], None, False),
        ("", ["Marko", "Jovan"], None, True),
        ("", [], None, False),
    ],
)
async def test_mark_matches_one_person_without_guessing(
    birthday_notion, monkeypatch, name, names, matched, ambiguous
):
    for item in names:
        birthday_notion.add(item)
    pool = SimpleNamespace(execute=AsyncMock())
    monkeypatch.setattr(birthdays.db, "pool", lambda: pool)
    result = await birthdays.mark_greeted(name)
    assert result["ambiguous"] is ambiguous
    assert [p["name"] for p in result["matched"]] == ([matched] if matched else [])
    assert pool.execute.await_count == bool(matched)


@pytest.mark.parametrize(
    "tool,args",
    [("birthdays_today", {}), ("birthdays_upcoming", {}), ("birthday_mark_greeted", {"name": ""})],
)
async def test_birthdays_requirements_and_api_failure(
    birthday_notion, respx_mock, monkeypatch, tool, args
):
    n = birthday_notion
    respx_mock.get(f"{n.base}/databases/{n.database}").respond(
        403, json={"code": "restricted_resource", "message": "Nema pristupa"}
    )
    assert (await registry.execute(tool, args)).is_error
    monkeypatch.setattr(settings(), "notion_birthdays_db_id", None)
    assert "NOTION_BIRTHDAYS_DB_ID" in registry._TOOLS[tool].disabled_reason()


async def test_invalid_birthday_date_is_explicit(birthday_notion):
    birthday_notion.add(born="1990-02-30")
    out = await registry.execute("birthdays_today", {})
    assert out.is_error and "datum" in out.text


@pytest.mark.parametrize(
    "name,args",
    [
        ("birthdays_upcoming", {"days": -1}),
        ("birthdays_upcoming", {"days": 367}),
        ("birthday_mark_greeted", {}),
        ("monitor_uptime", {"dana": 0}),
        ("monitor_uptime", {"dana": 367}),
        ("monitor_check_sites", {"url": "http://localhost"}),
    ],
)
async def test_new_tools_reject_invalid_arguments(birthday_notion, monkeypatch, name, args):
    monkeypatch.setattr(settings(), "notion_clients_db_id", "test")
    assert (await registry.execute(name, args)).is_error
    assert not birthday_notion.query.called

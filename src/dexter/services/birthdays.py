"""Godišnji datumi iz Notion-a i nezavisna evidencija čestitanja po lokalnom danu."""

import calendar
from datetime import date, timedelta

from dexter import db
from dexter.config import settings
from dexter.pismo import u_latinicu
from dexter.proactive_time import local_now
from dexter.services import notion

REQUIRES = ["NOTION_API_KEY", "NOTION_BIRTHDAYS_DB_ID"]
DAYS = ("ponedeljak", "utorak", "sreda", "četvrtak", "petak", "subota", "nedelja")


def today() -> date:
    return local_now().date()


def anniversary(born: date, year: int) -> date:
    day = 28 if born.month == 2 and born.day == 29 and not calendar.isleap(year) else born.day
    return date(year, born.month, day)


def age_turning(born: date, year: int) -> int | None:
    age = year - born.year
    return age if 0 < age < 120 else None


async def people() -> list[dict]:
    async with notion.client() as api:
        source = await notion.database_source(
            api, settings().notion_birthdays_db_id, "NOTION_BIRTHDAYS_DB_ID"
        )
        result = []
        async for page in notion.query_pages(api, source):
            props = page.get("properties", {})
            value = (props.get("Rođendan", {}).get("date") or {}).get("start")
            if not value:
                continue
            try:
                born = date.fromisoformat(value[:10])
            except ValueError as exc:
                raise ValueError(
                    "Neispravan datum u Notion koloni Rođendan; ispravi taj red."
                ) from exc
            result.append(
                {
                    "id": page["id"],
                    "url": page.get("url"),
                    "name": u_latinicu(
                        notion.rich_text(props.get("Ime i prezime", {}).get("title", []))
                    ),
                    "date": born.isoformat(),
                    "relation": u_latinicu(
                        (props.get("Odnos", {}).get("select") or {}).get("name")
                    ),
                    "phone": props.get("Telefon", {}).get("phone_number"),
                    "giftIdea": u_latinicu(
                        notion.rich_text(props.get("Ideja za poklon", {}).get("rich_text", []))
                    ),
                    "note": u_latinicu(
                        notion.rich_text(props.get("Napomena", {}).get("rich_text", []))
                    ),
                }
            )
        return result


async def birthdays_today(current: date | None = None) -> list[dict]:
    current = current or today()
    return [
        {**person, "age": age_turning(date.fromisoformat(person["date"]), current.year)}
        for person in await people()
        if anniversary(date.fromisoformat(person["date"]), current.year) == current
    ]


async def upcoming(days: int = 30, current: date | None = None) -> list[dict]:
    if not 0 <= days <= 366:
        raise ValueError("Period rođendana mora biti 0–366 dana.")
    current, result = current or today(), []
    for person in await people():
        born = date.fromisoformat(person["date"])
        when = anniversary(born, current.year)
        if when < current:
            when = anniversary(born, current.year + 1)
        distance = (when - current).days
        if distance <= days:
            result.append({**person, "inDays": distance, "age": age_turning(born, when.year)})
    return sorted(result, key=lambda person: person["inDays"])


async def this_week() -> list[dict]:
    current = today()
    return [
        {
            **person,
            "dayName": DAYS[(when := current + timedelta(days=person["inDays"])).weekday()],
            "dayDate": f"{when.day}.{when.month}.",
        }
        for person in await upcoming(6, current)
    ]


async def mark_greeted(name: str) -> dict:
    current = today()
    persons = await birthdays_today(current)
    needle = u_latinicu(name).strip().casefold()
    exact = [person for person in persons if person["name"].casefold() == needle]
    hits = exact or [person for person in persons if needle in person["name"].casefold()]
    if len(hits) != 1:
        return {
            "matched": [],
            "ambiguous": len(hits) > 1,
            "candidates": [person["name"] for person in hits or persons],
            "reason": "Danas niko ne slavi." if not persons else "Preciziraj kome si čestitao.",
        }
    person = hits[0]
    await db.pool().execute(
        "INSERT INTO birthday_greetings(greeted_on,person_id,person_name) VALUES($1,$2,$3) "
        "ON CONFLICT(greeted_on,person_id) DO UPDATE SET person_name=$3",
        current,
        person["id"],
        person["name"],
    )
    return {
        "matched": [{"id": person["id"], "name": person["name"]}],
        "ambiguous": False,
        "candidates": [],
    }


async def ungreeted_today() -> list[dict]:
    current = today()
    greeted = {
        row["person_id"]
        for row in await db.pool().fetch(
            "SELECT person_id FROM birthday_greetings WHERE greeted_on=$1", current
        )
    }
    return [person for person in await birthdays_today(current) if person["id"] not in greeted]

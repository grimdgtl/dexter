"""Dnevni Notion redovi: lokalni datumi, paginacija i trajna zaštita od duplikata."""

import hashlib
from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from notion_client import APIResponseError

from dexter import db
from dexter.config import settings

DAYS = ("Ponedeljak", "Utorak", "Sreda", "Četvrtak", "Petak", "Subota", "Nedelja")


def day(value: str | None = None) -> date:
    return (
        date.fromisoformat(value) if value else datetime.now(ZoneInfo(settings().timezone)).date()
    )


async def source(api, env: str) -> str:
    database_id = getattr(settings(), env.lower())
    if not database_id:
        raise ValueError(f"Nedostaje {env}.")
    database = await api.databases.retrieve(database_id=database_id)
    sources = database.get("data_sources", [])
    if len(sources) != 1:
        raise ValueError(f"{env}: baza mora imati tačno jedan izvor podataka (data source).")
    return sources[0]["id"]


async def query(api, source_id: str, filter_: dict) -> list[dict]:
    rows, seen, cursor = [], set(), None
    while True:
        response = await api.data_sources.query(
            data_source_id=source_id,
            filter=filter_,
            sorts=[{"property": "Datum", "direction": "ascending"}],
            page_size=100,
            **({"start_cursor": cursor} if cursor else {}),
        )
        rows.extend(
            p for p in response["results"] if not p.get("archived") and not p.get("in_trash")
        )
        if not response.get("has_more"):
            return rows
        cursor = response.get("next_cursor")
        if not cursor or cursor in seen:
            raise RuntimeError("Notion je vratio neispravnu paginaciju dnevnih redova.")
        seen.add(cursor)


async def find(api, source_id: str, datum: str) -> dict | None:
    rows = await query(api, source_id, {"property": "Datum", "date": {"equals": datum}})
    if len(rows) > 1:
        raise ValueError(f"Postoji više redova za {datum}; prvo razreši duplikate u Notion-u.")
    return rows[0] if rows else None


async def period(api, source_id: str, start: str, end: str) -> list[dict]:
    return await query(
        api,
        source_id,
        {
            "and": [
                {"property": "Datum", "date": {"on_or_after": start}},
                {"property": "Datum", "date": {"on_or_before": end}},
            ]
        },
    )


async def ensure(api, source_id: str, datum: str, extra: dict | None = None) -> tuple[dict, bool]:
    existing = await find(api, source_id, datum)
    if existing:
        return existing, True
    key = "notion:day:" + hashlib.sha256(f"{UUID(source_id)}\n{datum}".encode()).hexdigest()
    # Notion nema jedinstven datum; trajni ključ sprečava paralelan i neizvestan ponovni create.
    claimed = await db.pool().fetchval(
        "INSERT INTO kv_state(key,value) VALUES($1,$2) ON CONFLICT DO NOTHING RETURNING key",
        key,
        {"status": "pokusano"},
    )
    if not claimed:
        state = await db.pool().fetchval("SELECT value FROM kv_state WHERE key=$1", key)
        if state and state.get("page_id"):
            page = await api.pages.retrieve(page_id=state["page_id"])
            parent = page.get("parent", {})
            if (
                parent.get("data_source_id")
                and UUID(parent["data_source_id"]) == UUID(source_id)
                and not page.get("archived")
                and not page.get("in_trash")
                and (page.get("properties", {}).get("Datum", {}).get("date") or {}).get("start")
                == datum
            ):
                return page, True
        raise RuntimeError(
            f"Upis za {datum} je već pokušavan, a red nije potvrđen. "
            "Proveri Notion; novi red nije ponovo kreiran."
        )
    properties = {
        "Dan": {"title": [{"text": {"content": DAYS[day(datum).weekday()]}}]},
        "Datum": {"date": {"start": datum}},
        **(extra or {}),
    }
    try:
        page = await api.pages.create(
            parent={"type": "data_source_id", "data_source_id": source_id}, properties=properties
        )
    except APIResponseError as exc:
        if 400 <= exc.status < 500 and exc.status != 408:
            await db.pool().execute("DELETE FROM kv_state WHERE key=$1", key)
        raise
    await db.pool().execute(
        "UPDATE kv_state SET value=$2, updated_at=now() WHERE key=$1",
        key,
        {"status": "kreiran", "page_id": page["id"]},
    )
    return page, False

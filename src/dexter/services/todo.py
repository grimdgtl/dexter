"""Lični zadaci u Notion-u i nedeljni upis koji preživljava retry i restart."""

import hashlib
from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from notion_client import APIResponseError

from dexter import db
from dexter.config import settings
from dexter.pismo import u_latinicu
from dexter.services import notion

REQUIRES = ["NOTION_API_KEY", "NOTION_TODO_DB_ID"]


def available() -> bool:
    return all(getattr(settings(), key.lower()) for key in REQUIRES)


async def data_source(api) -> str:
    database_id = settings().notion_todo_db_id
    if not database_id:
        raise ValueError("Nedostaje NOTION_TODO_DB_ID.")
    database = await api.databases.retrieve(database_id=database_id)
    sources = database.get("data_sources", [])
    # Ne biramo naslepo drugu tabelu kada je Notion baza višeznačna.
    if len(sources) != 1:
        raise ValueError("To-do baza mora imati tačno jedan izvor podataka (data source).")
    return sources[0]["id"]


def task_data(page: dict) -> dict:
    props = page.get("properties", {})
    return {
        "id": page["id"],
        "url": page.get("url"),
        "zadatak": u_latinicu(notion.rich_text(props.get("Zadatak", {}).get("title", []))),
        "status": u_latinicu((props.get("Status", {}).get("status") or {}).get("name")),
        "oblast": u_latinicu((props.get("Oblast", {}).get("select") or {}).get("name")),
        "prioritet": u_latinicu((props.get("Prioritet", {}).get("select") or {}).get("name")),
        "rok": (props.get("Rok", {}).get("date") or {}).get("start"),
    }


async def list_tasks(status: str | None = None, limit: int = 25) -> list[dict]:
    filter_ = {
        "property": "Status",
        "status": {"equals": status} if status else {"does_not_equal": "Done"},
    }
    async with notion.client() as api:
        source = await data_source(api)
        rows, seen, cursor = [], set(), None
        while len(rows) < limit:
            response = await api.data_sources.query(
                data_source_id=source,
                filter=filter_,
                page_size=min(100, limit - len(rows)),
                **({"start_cursor": cursor} if cursor else {}),
            )
            rows.extend(
                task_data(p)
                for p in response["results"]
                if not p.get("archived") and not p.get("in_trash")
            )
            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor")
            if not cursor or cursor in seen:
                raise RuntimeError("Notion je vratio neispravnu paginaciju zadataka.")
            seen.add(cursor)
        return rows[:limit]


async def _add(api, source: str, zadatak: str, oblast=None, prioritet=None, rok=None) -> dict:
    properties = {
        "Zadatak": {"title": [{"text": {"content": u_latinicu(zadatak)}}]},
        "Status": {"status": {"name": "Not started"}},
    }
    if oblast:
        properties["Oblast"] = {"select": {"name": oblast}}
    if prioritet:
        properties["Prioritet"] = {"select": {"name": prioritet}}
    if rok:
        properties["Rok"] = {"date": {"start": rok}}
    return task_data(
        await api.pages.create(
            parent={"type": "data_source_id", "data_source_id": source}, properties=properties
        )
    )


async def add_task(zadatak: str, oblast=None, prioritet=None, rok=None) -> dict:
    async with notion.client() as api:
        return await _add(api, await data_source(api), zadatak, oblast, prioritet, rok)


async def set_status(task_id: str, status: str) -> dict:
    async with notion.client() as api:
        source = await data_source(api)
        page = await api.pages.retrieve(page_id=task_id)
        parent = page.get("parent", {})
        if UUID(parent.get("data_source_id", UUID(int=0).hex)) != UUID(source):
            raise ValueError("Zadatak ne pripada podešenoj ličnoj To-do listi.")
        if page.get("archived") or page.get("in_trash"):
            raise ValueError("Zadatak je u arhivi ili korpi.")
        return task_data(
            await api.pages.update(
                page_id=task_id, properties={"Status": {"status": {"name": status}}}
            )
        )


def week_window(day: date | None = None) -> tuple[date, date]:
    day = day or datetime.now(ZoneInfo(settings().timezone)).date()
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)


async def create_weekly(day: date | None = None) -> dict:
    start, end = week_window(day)
    title = u_latinicu(settings().weekly_task_title.strip())
    if not title:
        raise ValueError("WEEKLY_TASK_TITLE ne sme biti prazan.")
    async with notion.client() as api:
        source = await data_source(api)
        response = await api.data_sources.query(
            data_source_id=source,
            page_size=1,
            filter={
                "and": [
                    {"property": "Zadatak", "title": {"contains": title}},
                    {"property": "Rok", "date": {"on_or_after": start.isoformat()}},
                    {"property": "Rok", "date": {"on_or_before": end.isoformat()}},
                ]
            },
        )
        if response["results"]:
            return {**task_data(response["results"][0]), "vecPostojao": True}
        key = (
            "todo:weekly:"
            + hashlib.sha256(f"{UUID(source)}\n{start}\n{title}".encode()).hexdigest()
        )
        # Jedinstven upis sprečava dva procesa i neizvestan HTTP retry da naprave duplikat.
        claimed = await db.pool().fetchval(
            "INSERT INTO kv_state(key,value) VALUES($1,$2) ON CONFLICT DO NOTHING RETURNING key",
            key,
            {"status": "pokusano"},
        )
        if not claimed:
            state = await db.pool().fetchval("SELECT value FROM kv_state WHERE key=$1", key)
            if state and state.get("task"):
                return {**state["task"], "vecPostojao": True}
            raise RuntimeError(
                "Nedeljni upis je već pokušavan, a ishod nije potvrđen. "
                "Proveri To-do listu; novi zadatak nije automatski ponovljen."
            )
        try:
            task = await _add(api, source, title, "Ljudi", "Srednji", end.isoformat())
        except APIResponseError as exc:
            # Odbijen zahtev nije upisao red; mrežna greška i 5xx ostaju neizvesni.
            if 400 <= exc.status < 500 and exc.status != 408:
                await db.pool().execute("DELETE FROM kv_state WHERE key=$1", key)
            raise
        await db.pool().execute(
            "UPDATE kv_state SET value=$2, updated_at=now() WHERE key=$1",
            key,
            {"status": "kreiran", "task": task},
        )
        return {**task, "vecPostojao": False}


async def find_weekly(day: date | None = None) -> dict | None:
    start, end = week_window(day)
    async with notion.client() as api:
        async for page in notion.query_pages(
            api,
            await data_source(api),
            {
                "and": [
                    {
                        "property": "Zadatak",
                        "title": {"contains": u_latinicu(settings().weekly_task_title.strip())},
                    },
                    {"property": "Rok", "date": {"on_or_after": start.isoformat()}},
                    {"property": "Rok", "date": {"on_or_before": end.isoformat()}},
                ]
            },
            limit=1,
        ):
            return task_data(page)
    return None

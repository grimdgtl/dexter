"""Poslovni TASK BOARD i podstranice Knowledge Base-a iz v1."""

import logging
from uuid import UUID

from dexter.config import settings
from dexter.pismo import u_latinicu
from dexter.services import notion

TASK_REQUIRES = ["NOTION_API_KEY", "NOTION_TASKS_DB_ID"]
KB_REQUIRES = ["NOTION_API_KEY", "NOTION_KB_PAGE_ID"]
STATUSES = ("Not started", "In progress", "Done")
log = logging.getLogger(__name__)


async def task_source(api) -> str:
    return await notion.database_source(api, settings().notion_tasks_db_id, "NOTION_TASKS_DB_ID")


def task_row(page: dict) -> dict:
    props = page.get("properties", {})
    return {
        "id": page["id"],
        "url": page.get("url"),
        "title": u_latinicu(notion.rich_text(props.get("Name", {}).get("title", []))),
        "status": u_latinicu((props.get("Status", {}).get("status") or {}).get("name")),
    }


async def add_task(title: str, status: str = "Not started") -> dict:
    if status not in STATUSES:
        raise ValueError("Nepoznat status poslovnog zadatka.")
    async with notion.client() as api:
        return task_row(
            await api.pages.create(
                parent={"type": "data_source_id", "data_source_id": await task_source(api)},
                properties={
                    "Name": {"title": notion.text_fragments(title)},
                    "Status": {"status": {"name": status}},
                },
            )
        )


async def list_tasks(status: str | None = None, limit: int = 25) -> list[dict]:
    async with notion.client() as api:
        source_id = await task_source(api)
        filter_ = {"property": "Status", "status": {"equals": status}} if status else None
        return [task_row(p) async for p in notion.query_pages(api, source_id, filter_, limit)]


async def update_task(task_id: str, status: str) -> dict:
    if status not in STATUSES:
        raise ValueError("Nepoznat status poslovnog zadatka.")
    async with notion.client() as api:
        source_id = await task_source(api)
        page = await api.pages.retrieve(page_id=task_id)
        parent = page.get("parent", {})
        if UUID(parent.get("data_source_id", UUID(int=0).hex)) != UUID(source_id):
            raise ValueError("Zadatak ne pripada podešenom poslovnom TASK BOARD-u.")
        if page.get("archived") or page.get("in_trash"):
            raise ValueError("Zadatak je u arhivi ili korpi.")
        updated = await api.pages.update(
            page_id=task_id, properties={"Status": {"status": {"name": status}}}
        )
        return {key: value for key, value in task_row(updated).items() if key != "title"}


def paragraphs(content: str) -> list[dict]:
    content = u_latinicu(content)
    return [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {"type": "text", "text": {"content": line[i : i + 2000]}}
                    for i in range(0, len(line), 2000)
                ]
            },
        }
        for line in content.splitlines()
        if line.strip()
    ]


async def add_knowledge(title: str, content: str = "") -> dict:
    parent = settings().notion_kb_page_id
    if not parent:
        raise ValueError("Nedostaje NOTION_KB_PAGE_ID.")
    blocks = paragraphs(content)
    if len(blocks) > 1000:
        raise ValueError("Beleška može imati najviše 1000 nepraznih pasusa; podeli tekst.")
    async with notion.client() as api:
        page = await api.pages.create(
            parent={"type": "page_id", "page_id": parent},
            properties={"title": {"title": notion.text_fragments(title)}},
            children=blocks[:100],
        )
        result = {"id": page["id"], "url": page.get("url"), "title": u_latinicu(title)}
        for start in range(100, len(blocks), 100):
            try:
                await api.blocks.children.append(
                    block_id=page["id"], children=blocks[start : start + 100]
                )
            except Exception as exc:
                # Stranica već postoji; ponavljanje create-a bi sakrilo delimičan upis duplikatom.
                log.warning("KB dopuna nije potvrđena: %s", type(exc).__name__)
                return {
                    **result,
                    "status": "delimicno",
                    "potvrdjenoPasusa": start,
                    "ukupnoPasusa": len(blocks),
                    "napomena": "Stranica je kreirana, ali ostatak teksta nije potvrđen. "
                    "Proveri je preko linka; ne ponavljaj kreiranje cele beleške.",
                }
        return result

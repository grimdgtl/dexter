"""Notion čitanje: paginacija i obilazak ugnježdenih blokova."""

from collections.abc import AsyncIterator

from notion_client import AsyncClient

from dexter.config import settings
from dexter.pismo import u_latinicu


def client() -> AsyncClient:
    key = settings().notion_api_key
    if not key:
        raise RuntimeError("Nedostaje NOTION_API_KEY.")
    return AsyncClient(auth=key, notion_version="2025-09-03", timeout_ms=30000)


def title_of(obj: dict) -> str:
    rich = obj.get("title", [])
    if not rich:
        prop = next((p for p in obj.get("properties", {}).values() if p.get("type") == "title"), {})
        rich = prop.get("title", [])
    return u_latinicu(rich_text(rich) or "(bez naslova)")


def rich_text(items: list[dict]) -> str:
    return "".join(i.get("plain_text", i.get("text", {}).get("content", "")) for i in items)


def text_fragments(value: str) -> list[dict]:
    # Preslovljavanje može produžiti tekst; Notion granicu proveravamo tek posle njega.
    value = u_latinicu(value)
    return [{"text": {"content": value[i : i + 2000]}} for i in range(0, len(value), 2000)]


async def database_source(api: AsyncClient, database_id: str | None, env: str) -> str:
    if not database_id:
        raise ValueError(f"Nedostaje {env}.")
    database = await api.databases.retrieve(database_id=database_id)
    sources = database.get("data_sources", [])
    # Više tabela pod jednim database ID-jem nije dovoljan osnov za bezbedan upis.
    if len(sources) != 1:
        raise ValueError(f"{env}: baza mora imati tačno jedan izvor podataka (data source).")
    return sources[0]["id"]


async def query_pages(
    api: AsyncClient,
    source_id: str,
    filter_: dict | None = None,
    limit: int | None = None,
    sorts: list[dict] | None = None,
) -> AsyncIterator[dict]:
    cursor, seen, count = None, set(), 0
    while True:
        response = await api.data_sources.query(
            data_source_id=source_id,
            page_size=min(100, limit - count) if limit else 100,
            **({"filter": filter_} if filter_ else {}),
            **({"sorts": sorts} if sorts else {}),
            **({"start_cursor": cursor} if cursor else {}),
        )
        for page in response["results"]:
            if page.get("archived") or page.get("in_trash"):
                continue
            yield page
            count += 1
            if limit and count >= limit:
                return
        if not response.get("has_more"):
            return
        cursor = response.get("next_cursor")
        if not cursor or cursor in seen:
            raise ValueError("Notion je vratio neispravnu paginaciju baze.")
        seen.add(cursor)


async def search_pages(
    api: AsyncClient, query: str = "", limit: int | None = None
) -> AsyncIterator[dict]:
    cursor = None
    seen = set()
    count = 0
    while True:
        kwargs = {"query": query, "page_size": min(100, limit - count) if limit else 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        result = await api.search(**kwargs)
        for obj in result["results"]:
            yield obj
            count += 1
            if limit and count >= limit:
                return
        if not result.get("has_more"):
            return
        cursor = result.get("next_cursor")
        if not cursor or cursor in seen:
            raise RuntimeError("Notion je vratio neispravnu paginaciju.")
        seen.add(cursor)


async def read_blocks(api: AsyncClient, page_id: str, visited: set[str] | None = None) -> str:
    visited = visited if visited is not None else set()
    if page_id in visited:
        return ""
    visited.add(page_id)
    cursor = None
    cursors = set()
    lines = []
    while True:
        result = await api.blocks.children.list(
            block_id=page_id, page_size=100, start_cursor=cursor
        )
        for block in result["results"]:
            if block.get("archived") or block.get("in_trash"):
                continue
            kind = block.get("type", "")
            body = block.get(kind, {})
            text = rich_text(body.get("rich_text", []))
            if kind == "child_page":
                text = body.get("title", "")
            elif kind == "table_row":
                text = " | ".join(rich_text(cell) for cell in body.get("cells", []))
            elif kind in {"bookmark", "link_preview", "embed"}:
                text = body.get("url", "")
            if text:
                lines.append(text)
            if block.get("has_children") or kind == "child_page":
                lines.append(await read_blocks(api, block["id"], visited))
        if not result.get("has_more"):
            break
        cursor = result.get("next_cursor")
        if not cursor or cursor in cursors:
            raise RuntimeError("Notion je vratio neispravnu paginaciju blokova.")
        cursors.add(cursor)
    return u_latinicu("\n".join(line for line in lines if line))


async def search(query: str, limit: int = 10) -> list[dict]:
    async with client() as api:
        return [
            {
                "id": p["id"],
                "type": p["object"],
                "title": title_of(p),
                "url": p.get("url"),
                "lastEdited": p.get("last_edited_time"),
            }
            async for p in search_pages(api, query, limit)
        ]


async def read_page(page_id: str) -> dict:
    async with client() as api:
        return {"id": page_id, "text": await read_blocks(api, page_id)}

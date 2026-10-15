"""Osvežavanje indeksa samo iz potpuno pročitanih izvora."""

import asyncio

from apu.config import settings

_index_lock = asyncio.Lock()


def available() -> list[str]:
    return ["notion"] if settings().notion_api_key else []


async def reindex(source: str | None = None) -> dict:
    from apu.sources import notion

    names = available()
    if source is not None and source not in names:
        raise ValueError(f"Izvor {source} nije podešen.")
    async with _index_lock:
        return {name: await notion.reindex() for name in ([source] if source else names)}

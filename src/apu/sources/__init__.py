"""Osvežavanje indeksa samo iz potpuno pročitanih izvora."""

import asyncio

from apu.config import settings
from apu.services import google
from apu.services import mail as mail_service

_index_lock = asyncio.Lock()


def available() -> list[str]:
    names = ["notion"] if settings().notion_api_key else []
    if google.configured():
        names.append("drive")
    if mail_service.configured():
        names.append("mail")
    return names


async def reindex(source: str | None = None) -> dict:
    from apu.sources import drive, mail, notion

    names = available()
    if source is not None and source not in names:
        raise ValueError(f"Izvor {source} nije podešen.")
    async with _index_lock:
        runners = {"notion": notion.reindex, "drive": drive.reindex, "mail": mail.reindex}
        return {name: await runners[name]() for name in ([source] if source else names)}

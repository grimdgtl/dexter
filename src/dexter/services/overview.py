"""Čitanja za uvid ne šalju mejlove i ne menjaju kalendar, zadatke ni Seen oznake."""

import asyncio
from datetime import date, datetime

from imap_tools import AND, MailBox

from dexter.config import settings
from dexter.pismo import u_latinicu
from dexter.services import calendar as calendar_service
from dexter.services import notion


async def calendar(start: datetime, end: datetime) -> list[dict]:
    return [
        {
            "id": e["id"],
            "naslov": u_latinicu(e.get("summary", "(bez naslova)")),
            "početak": e.get("start", {}),
            "kraj": e.get("end", {}),
        }
        for e in await calendar_service.raw_events(start, end)
    ]


async def tasks() -> list[dict]:
    async with notion.client() as api:
        database = await api.databases.retrieve(database_id=settings().notion_tasks_db_id)
        sources = database.get("data_sources", [])
        if not sources:
            raise ValueError("TASK BOARD nije vratio data_sources.")
        rows = []
        for source in sources:
            cursor, seen = None, set()
            while True:
                data = await api.data_sources.query(
                    data_source_id=source["id"], page_size=100, start_cursor=cursor
                )
                for page in data["results"]:
                    if page.get("archived") or page.get("in_trash"):
                        continue
                    props = page.get("properties", {})
                    status = props.get("Status", {}).get("status", {}).get("name")
                    if status not in {"Not started", "In progress", "Done"}:
                        raise ValueError(
                            "TASK BOARD mora imati Status: Not started, In progress, Done."
                        )
                    due = (props.get("Rok", {}).get("date") or {}).get("start")
                    rows.append(
                        {
                            "id": page["id"],
                            "naslov": notion.title_of(page),
                            "status": status,
                            "rok": date.fromisoformat(due[:10]).isoformat() if due else None,
                            "izmenjeno": page.get("last_edited_time"),
                        }
                    )
                if not data.get("has_more"):
                    break
                cursor = data.get("next_cursor")
                if not cursor or cursor in seen:
                    raise ValueError("TASK BOARD ima neispravnu paginaciju.")
                seen.add(cursor)
        return rows


async def unread(limit=30) -> list[dict]:
    cfg = settings()

    def read():
        with MailBox(cfg.imap_host, port=cfg.imap_port, timeout=30) as box:
            box.login(cfg.imap_user, cfg.imap_password, initial_folder=None)
            box.folder.set("INBOX", readonly=True)
            return [
                {
                    "id": m.uid,
                    "od": u_latinicu(m.from_),
                    "naslov": u_latinicu(m.subject),
                    "datum": m.date.isoformat(),
                    "tekst": u_latinicu(m.text[:500]),
                    "označen": "\\Flagged" in m.flags,
                }
                for m in box.fetch(AND(seen=False), mark_seen=False, reverse=True, limit=limit)
            ]

    return await asyncio.to_thread(read)

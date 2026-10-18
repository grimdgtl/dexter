"""Trajan trag slanja sprečava duplikat kad retry ne zna da li je Telegram primio poruku."""

from contextlib import asynccontextmanager
from dataclasses import dataclass

from telegram.error import BadRequest, Forbidden, RetryAfter

from dexter import db, jobs
from dexter.config import settings
from dexter.pismo import u_latinicu
from dexter.proactive_time import local_now
from dexter.services import motivation


@dataclass
class Notice:
    text: str
    mail_key: str | None = None
    previous: list[str] | None = None
    notified: list[str] | None = None
    motivation: str | None = None


def now():
    execution = jobs.current.get()
    return local_now(execution[1] if execution else None)


def key(kind: str) -> str:
    execution = jobs.current.get()
    slot = str(execution[0]) if execution else now().strftime("%Y-%m-%dT%H:%M%z")
    return f"scheduled:delivery:{kind}:{slot}"


@asynccontextmanager
async def connection(conn=None):
    if conn is not None:
        yield conn
    else:
        async with db.pool().acquire() as borrowed:
            yield borrowed


async def put(conn, state_key, value):
    await conn.execute(
        "INSERT INTO kv_state(key,value) VALUES($1,$2) ON CONFLICT(key) "
        "DO UPDATE SET value=$2,updated_at=now()",
        state_key,
        value,
    )


def existing(state) -> bool:
    if state["status"] == "sent":
        return False
    raise RuntimeError("Ishod ranijeg Telegram slanja nije potvrđen; poruka nije poslata ponovo.")


async def dispatch(kind, bot, prepare, *, conn=None) -> bool:
    state_key = key(kind)
    async with connection(conn) as reader:
        state = await reader.fetchval("SELECT value FROM kv_state WHERE key=$1", state_key)
    if state:
        return existing(state)
    notice = await prepare()
    if notice is None:
        return False
    text = u_latinicu(notice.text).strip()
    if not text or len(text.encode("utf-16-le")) // 2 > 3900:
        raise ValueError("Zakazana poruka je prazna ili predugačka; ništa nije poslato.")
    state = {"status": "sending", "text": text}
    async with connection(conn) as writer:
        async with writer.transaction():
            claimed = await writer.fetchval(
                "INSERT INTO kv_state(key,value) VALUES($1,$2) ON CONFLICT DO NOTHING RETURNING key",
                state_key,
                state,
            )
            if not claimed:
                return existing(
                    await writer.fetchval("SELECT value FROM kv_state WHERE key=$1", state_key)
                )
            if notice.mail_key:
                await put(writer, notice.mail_key, notice.notified)
            if notice.motivation:
                await writer.execute("SELECT pg_advisory_xact_lock(42702027)")
                previous = [
                    row["text"]
                    for row in await writer.fetch(
                        "SELECT text FROM motivation_messages ORDER BY id DESC LIMIT $1",
                        settings().motivation_history,
                    )
                ]
                if motivation.repeated(notice.motivation, previous):
                    raise ValueError("Jutarnja poruka je u međuvremenu već pripremljena.")
                await writer.execute(
                    "INSERT INTO motivation_messages(text,delivery_key,status) VALUES($1,$2,'prepared')",
                    notice.motivation,
                    state_key,
                )
        try:
            reply = await bot.send_message(settings().telegram_owner_chat_id, text)
        except (BadRequest, Forbidden, RetryAfter):
            # Telegram je definitivno odbio zahtev, pa je nov pokušaj bezbedan.
            async with writer.transaction():
                await writer.execute("DELETE FROM kv_state WHERE key=$1", state_key)
                await writer.execute(
                    "DELETE FROM motivation_messages WHERE delivery_key=$1", state_key
                )
                if notice.mail_key:
                    await put(writer, notice.mail_key, notice.previous)
            raise
        except Exception as exc:
            await put(
                writer, state_key, {**state, "status": "unknown", "error": type(exc).__name__}
            )
            await writer.execute(
                "UPDATE motivation_messages SET status='unknown' WHERE delivery_key=$1", state_key
            )
            raise
        async with writer.transaction():
            mid = getattr(reply, "message_id", None)
            await put(
                writer,
                state_key,
                {**state, "status": "sent", "message_id": mid if isinstance(mid, int) else None},
            )
            if notice.motivation:
                await writer.execute("SELECT pg_advisory_xact_lock(42702027)")
                await writer.execute(
                    "UPDATE motivation_messages SET status='sent' WHERE delivery_key=$1", state_key
                )
                await writer.execute(
                    "DELETE FROM motivation_messages WHERE id IN (SELECT id FROM motivation_messages ORDER BY id DESC OFFSET $1)",
                    settings().motivation_history,
                )
            await writer.execute(
                "DELETE FROM kv_state WHERE key LIKE 'scheduled:delivery:%' "
                "AND updated_at < now() - interval '30 days'"
            )
    return True

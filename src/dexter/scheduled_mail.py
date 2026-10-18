"""Brifing i satna provera dele stanje; samo nepročitani UID-jevi ostaju prijavljeni."""

import hashlib
from contextlib import asynccontextmanager
from dataclasses import dataclass

from dexter import db
from dexter.config import settings
from dexter.scheduled_delivery import Notice, put
from dexter.services import mail


def account_key() -> str:
    cfg = settings()
    value = f"{cfg.imap_host}:{cfg.imap_port}\n{cfg.imap_user}\nINBOX"
    return "mail:notified:" + hashlib.sha256(value.encode()).hexdigest()


@asynccontextmanager
async def locked():
    lock = int.from_bytes(hashlib.sha256(account_key().encode()).digest()[:8], "big", signed=True)
    async with db.pool().acquire() as conn:
        await conn.execute("SELECT pg_advisory_lock($1::bigint)", lock)
        try:
            yield conn
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1::bigint)", lock)


@dataclass
class Snapshot:
    key: str
    data: dict
    previous: list[str]

    def fresh(self) -> list[dict]:
        return [m for m in self.data["messages"] if str(m["uid"]) not in self.previous]

    def notice(self, text: str, messages: list[dict]) -> Notice:
        return Notice(
            text,
            self.key,
            self.previous,
            sorted(set(self.previous) | {str(m["uid"]) for m in messages}),
        )


async def read(conn) -> Snapshot:
    data = await mail.notification_snapshot()
    state_key = f"{account_key()}:{data['uidvalidity']}"
    previous = await conn.fetchval("SELECT value FROM kv_state WHERE key=$1", state_key) or []
    previous = sorted(set(previous) & set(data["uids"]))
    # Limit prikaza nije dokaz da su stariji mejlovi pročitani: čistimo prema celom UID spisku.
    await put(conn, state_key, previous)
    return Snapshot(state_key, data, previous)

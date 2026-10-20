"""Kratko čekanje sledećeg priloga preživljava restart bez trajnog režima razgovora."""

from dexter.db import pool


def key(chat_id: int) -> str:
    return f"contract:intake:{chat_id}"


async def arm(chat_id: int, message_id: int) -> None:
    await pool().execute(
        """INSERT INTO kv_state(key,value) VALUES($1,$2)
        ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_at=now()""",
        key(chat_id),
        {"after_message_id": message_id},
    )


async def consume(chat_id: int, message_id: int) -> bool:
    # Jedan prilog sme da preuzme zahtev; stara/ponovljena poruka ga ne troši.
    return bool(
        await pool().fetchval(
            """DELETE FROM kv_state WHERE key=$1
            AND updated_at > now() - interval '10 minutes'
            AND (value->>'after_message_id')::bigint < $2 RETURNING key""",
            key(chat_id),
            message_id,
        )
    )


async def cancel(chat_id: int) -> None:
    await pool().execute("DELETE FROM kv_state WHERE key=$1", key(chat_id))

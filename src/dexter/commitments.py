"""Obaveza se čuva samo uz proverljiv citat korisnika i konkretan rok."""

import hashlib
import json
from datetime import date, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, field_validator

from dexter.db import pool
from dexter.pismo import u_latinicu
from dexter.proactive_time import local_now, quiet


class Commitment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tekst: str = Field(min_length=5, max_length=1000)
    osoba: str | None = Field(None, max_length=200)
    rok: date
    dokaz: str = Field(min_length=5, max_length=1500)

    @field_validator("tekst", "osoba", "dokaz")
    @classmethod
    def latin(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Polje ne sme biti samo razmak.")
        return u_latinicu(value).strip() if value else value


def normalized(text):
    return " ".join(u_latinicu(text).casefold().split())


async def save(item: Commitment, user_text: str, *, remind_on: date | None = None) -> bool:
    if normalized(item.dokaz) not in normalized(user_text):
        raise ValueError("Obaveza nema citat iz stvarne korisnikove poruke.")
    fingerprint = hashlib.sha256(
        json.dumps(
            [
                normalized(item.tekst),
                normalized(item.osoba or ""),
                item.rok.isoformat(),
            ]
        ).encode()
    ).hexdigest()
    result = await pool().fetchval(
        """INSERT INTO commitments (tekst,osoba,rok,dokaz,fingerprint,remind_on)
           VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (fingerprint) DO NOTHING RETURNING id""",
        item.tekst,
        item.osoba,
        item.rok,
        item.dokaz,
        fingerprint,
        remind_on,
    )
    return result is not None


async def list_all(status: str = "open") -> list[dict]:
    rows = await pool().fetch(
        "SELECT id,tekst,osoba,rok,status,done_at FROM commitments WHERE ($1='all' OR status=$1) ORDER BY rok,id",
        status,
    )
    return [dict(row) for row in rows]


async def done(item_id: int) -> bool:
    return (
        await pool().fetchval(
            "UPDATE commitments SET status='done',done_at=COALESCE(done_at,now()) WHERE id=$1 RETURNING id",
            item_id,
        )
        is not None
    )


async def remind(bot, now: datetime | None = None) -> int:
    from dexter import feedback
    from dexter.config import settings

    reference = now
    now = local_now(reference)
    if quiet(now):
        return 0
    rows = await pool().fetch(
        "SELECT id FROM commitments WHERE status='open' AND COALESCE(remind_on,rok-1)=$1 AND reminder_claimed_at IS NULL ORDER BY id",
        now.date(),
    )
    sent = 0
    for row in rows:
        current = local_now(reference)
        if quiet(current) or current.date() != now.date():
            break
        # Telegram nema idempotency key; claim pre mreže sprečava duplikat pri retry-u.
        item = await pool().fetchrow(
            """UPDATE commitments SET reminder_claimed_at=$2 WHERE id=$1 AND status='open'
               AND reminder_claimed_at IS NULL RETURNING *""",
            row["id"],
            now,
        )
        if not item:
            continue
        label = (
            "za sutra"
            if item["rok"] == now.date() + timedelta(days=1)
            else "za danas"
            if item["rok"] == now.date()
            else "za rok"
        )
        text = u_latinicu(
            f"Podsetnik {label} ({item['rok']}): {item['tekst']}"
            + (f" — {item['osoba']}" if item["osoba"] else "")
        )
        try:
            message = await bot.send_message(
                settings().telegram_owner_chat_id,
                text,
                reply_markup=feedback.keyboard("commitment", item["id"]),
            )
        except Exception as exc:
            await pool().execute(
                "UPDATE commitments SET reminder_error=$2 WHERE id=$1",
                item["id"],
                u_latinicu(str(exc))[:1000],
            )
            raise
        await pool().execute(
            "UPDATE commitments SET reminder_sent_at=$2,reminder_message_id=$3,reminder_text=$4 WHERE id=$1",
            item["id"],
            now,
            getattr(message, "message_id", None),
            text,
        )
        sent += 1
    return sent

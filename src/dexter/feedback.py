"""Ocene pripadaju stvarno isporučenim porukama i prihvataju se samo od vlasnika."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from dexter.config import settings
from dexter.db import pool
from dexter.pismo import u_latinicu


def keyboard(kind: str, source_id: int, rating: int | None = None):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "👍 ✓" if rating == 1 else "👍", callback_data=f"vote:{kind}:{source_id}:1"
                ),
                InlineKeyboardButton(
                    "👎 ✓" if rating == -1 else "👎", callback_data=f"vote:{kind}:{source_id}:-1"
                ),
            ]
        ]
    )


async def record(kind, source_id, rating, *, chat_id, message_id) -> bool:
    if chat_id != settings().telegram_owner_chat_id or rating not in {-1, 1} or source_id < 1:
        return False
    if kind in {"daily", "weekly"}:
        valid = await pool().fetchval(
            "SELECT EXISTS(SELECT 1 FROM proactive_runs WHERE id=$1 AND kind=$2 AND telegram_message_id=$3 AND status='sent')",
            source_id,
            kind,
            message_id,
        )
    elif kind == "commitment":
        valid = await pool().fetchval(
            "SELECT EXISTS(SELECT 1 FROM commitments WHERE id=$1 AND reminder_message_id=$2 AND reminder_sent_at IS NOT NULL)",
            source_id,
            message_id,
        )
    else:
        return False
    if not valid:
        return False
    await pool().execute(
        """INSERT INTO proactive_feedback (kind,source_id,rating) VALUES ($1,$2,$3)
           ON CONFLICT (kind,source_id) DO UPDATE SET rating=EXCLUDED.rating,updated_at=now()""",
        kind,
        source_id,
        rating,
    )
    return True


async def recent() -> list[dict]:
    rows = await pool().fetch(
        """SELECT f.kind,f.rating,f.updated_at,
                  CASE WHEN f.kind='commitment' THEN c.reminder_text ELSE r.decision->>'poruka' END AS poruka
           FROM proactive_feedback f
           LEFT JOIN proactive_runs r ON f.kind=r.kind AND f.source_id=r.id AND r.status='sent'
           LEFT JOIN commitments c ON f.kind='commitment' AND f.source_id=c.id
           WHERE (r.id IS NOT NULL OR c.reminder_sent_at IS NOT NULL)
           ORDER BY f.updated_at DESC,f.kind,f.source_id DESC LIMIT 10""",
    )
    return [
        {
            "vrsta": r["kind"],
            "ocena": r["rating"],
            "vreme": r["updated_at"].isoformat(),
            "poruka": u_latinicu(r["poruka"] or ""),
        }
        for r in rows
    ]


async def on_vote(update, ctx):
    if (
        update.effective_chat is None
        or update.effective_chat.id != settings().telegram_owner_chat_id
    ):
        return
    query = update.callback_query
    try:
        prefix, kind, source_id, rating = query.data.split(":")
        if prefix != "vote" or query.message is None:
            raise ValueError("Neispravno dugme.")
        source_id, rating = int(source_id), int(rating)
        saved = await record(
            kind,
            source_id,
            rating,
            chat_id=update.effective_chat.id,
            message_id=query.message.message_id,
        )
    except (ValueError, TypeError):
        saved = False
    if not saved:
        await query.answer("Ocena nije povezana sa dostupnom proaktivnom porukom.")
        return
    await query.answer("Ocena je sačuvana.")
    await query.edit_message_reply_markup(reply_markup=keyboard(kind, source_id, rating))

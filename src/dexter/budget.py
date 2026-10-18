"""Meki dnevni budžet: upozorenja su trajna, a preostali pozivi koriste brzi model."""

import logging
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from dexter.config import settings
from dexter.db import pool
from dexter.pismo import u_latinicu

log = logging.getLogger(__name__)
_bot = None


def configure(bot):
    global _bot
    _bot = bot


async def snapshot():
    tz = ZoneInfo(settings().timezone)
    day = datetime.now(tz).date()
    spent = await pool().fetchval(
        "SELECT COALESCE(sum(cost_usd),0) FROM usage WHERE created_at >= $1 AND created_at < $2",
        datetime.combine(day, time.min, tz),
        datetime.combine(day + timedelta(days=1), time.min, tz),
    )
    return day, spent


async def notify(day, spent, limit):
    if _bot is None or spent < limit * Decimal("0.8"):
        return
    key = f"daily_budget:{settings().telegram_owner_chat_id}:{day}"
    async with pool().acquire() as conn, conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", key)
        state = await conn.fetchval("SELECT value FROM kv_state WHERE key=$1", key) or {}
        level = "100" if spent >= limit else "80"
        if state.get(level):
            return
        text = f"💰 Dnevni budžet: ${spent:.4f} od ${limit:.4f}. " + (
            "Dostignuto je 100%; svi modeli koriste brzi model do lokalne ponoći."
            if level == "100"
            else "Dostignuto je 80% dnevnog budžeta."
        )
        await _bot.send_message(settings().telegram_owner_chat_id, u_latinicu(text))
        state[level] = True
        if level == "100":
            state["80"] = True
        await conn.execute(
            """INSERT INTO kv_state (key,value) VALUES ($1,$2) ON CONFLICT (key)
               DO UPDATE SET value=EXCLUDED.value, updated_at=now()""",
            key,
            state,
        )


async def model_for(requested: str | None = None) -> str | None:
    limit = settings().daily_budget_usd
    if limit is None:
        return requested
    try:
        day, spent = await snapshot()
    except Exception:
        log.exception("Ne mogu da proverim dnevni budžet; koristim brzi model.")
        return settings().model_fast if requested is not None else None
    try:
        await notify(day, spent, limit)
    except Exception:
        log.exception("Ne mogu da pošaljem upozorenje o budžetu; pokušaću ponovo.")
    return settings().model_fast if requested is not None and spent >= limit else requested

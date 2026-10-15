"""Ponavljanje zakazanih poslova i trajna evidencija ishoda."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from zoneinfo import ZoneInfo

from telegram import Bot

from apu.config import settings
from apu.db import pool
from apu.pismo import u_latinicu

log = logging.getLogger(__name__)


async def run_job(
    ime: str,
    fn: Callable[[], Awaitable[Any]],
    *,
    bot: Bot,
    attempts: int = 3,
    delay: float = 30,
) -> Any:
    if not 1 <= attempts <= 3 or delay < 0:
        raise ValueError("Dozvoljeno je 1–3 pokušaja i nenegativan razmak.")
    run_id = await pool().fetchval("INSERT INTO job_runs (ime) VALUES ($1) RETURNING id", ime)
    error = None
    result = None
    ok = False
    try:
        for attempt in range(1, attempts + 1):
            await pool().execute("UPDATE job_runs SET pokusaja = $2 WHERE id = $1", run_id, attempt)
            try:
                result = await fn()
            except Exception as exc:
                error = u_latinicu(str(exc))[:3000]
                log.exception("Posao %s, pokušaj %s/%s", ime, attempt, attempts)
                if attempt < attempts:
                    await asyncio.sleep(delay * 2 ** (attempt - 1))
            else:
                ok, error = True, None
                break
    except asyncio.CancelledError:
        await pool().execute(
            "UPDATE job_runs SET kraj = now(), ok = false, greska = 'Otkazano' WHERE id = $1",
            run_id,
        )
        raise
    # Upis ishoda ne ponavlja već izvršenu akciju ako sama baza zakaže.
    await pool().execute(
        "UPDATE job_runs SET kraj = now(), ok = $2, greska = $3 WHERE id = $1", run_id, ok, error
    )
    if not ok:
        try:
            await bot.send_message(
                settings().telegram_owner_chat_id,
                u_latinicu(
                    f'⚠️ Posao "{ime}" nije uspeo ni iz {attempts} pokušaja.\n\nGreška: {error}'
                ),
            )
        except Exception:
            log.exception("Slanje obaveštenja za posao %s nije uspelo", ime)
    return result


async def report(hours: int = 24) -> str:
    if not 1 <= hours <= 8760:
        raise ValueError("Broj sati mora biti između 1 i 8760.")
    rows = await pool().fetch(
        """SELECT ime, count(*) AS ukupno,
        count(*) FILTER (WHERE ok) AS uspeha,
        count(*) FILTER (WHERE ok = false) AS neuspeha,
        count(*) FILTER (WHERE ok IS NULL) AS u_toku, max(start) AS poslednje,
        (array_agg(greska ORDER BY start DESC) FILTER (WHERE greska IS NOT NULL))[1] AS greska
        FROM job_runs WHERE start >= now() - make_interval(hours => $1)
        GROUP BY ime ORDER BY count(*) FILTER (WHERE ok = false) DESC, ime""",
        hours,
    )
    if not rows:
        return "Poslovi: nema zabeleženih pokretanja u tom periodu."
    lines = [f"Poslovi u poslednjih {hours}h:"]
    for row in rows:
        time = row["poslednje"].astimezone(ZoneInfo(settings().timezone))
        lines.append(
            f"• {row['ime']}: {row['uspeha']}/{row['ukupno']} uspeha, "
            f"{row['neuspeha']} neuspeha, {row['u_toku']} u toku; {time:%d.%m.%Y %H:%M}"
        )
        if row["greska"]:
            lines.append(f"  Poslednja greška: {row['greska']}")
    return "\n".join(lines)

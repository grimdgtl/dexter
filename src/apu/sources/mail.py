"""Mejl indeks je izveden podatak; sanduče i oznake poruka se ne menjaju."""

from contextlib import aclosing
from datetime import datetime
from zoneinfo import ZoneInfo

from apu.config import settings
from apu.rag import store
from apu.services import mail


async def reindex() -> dict:
    cfg = settings()
    since = mail.months_ago(datetime.now(ZoneInfo(cfg.timezone)).date(), cfg.mail_index_months)
    alive = set()
    indexed = skipped = skipped_attachments = 0
    async with aclosing(mail.documents(since)) as documents:
        async for doc in documents:
            n = await store.upsert_document(doc.id, "mail", doc.title, doc.text)
            alive.add(doc.id)
            indexed += bool(n)
            skipped += not n
            skipped_attachments += doc.skipped_attachments
    # Greška bilo kog foldera sprečava čišćenje starog indeksa.
    removed = await store.remove_missing("mail", alive)
    return {
        "indeksirano": indexed,
        "preskoceno": skipped,
        "obrisano": removed,
        "ukupno": len(alive),
        "preskoceni_prilozi": skipped_attachments,
    }

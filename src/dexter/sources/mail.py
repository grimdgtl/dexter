"""Mejl indeks je izveden podatak; sanduče i oznake poruka se ne menjaju."""

from contextlib import aclosing
from datetime import datetime
from zoneinfo import ZoneInfo

from dexter.config import settings
from dexter.rag import store
from dexter.services import mail


async def reindex() -> dict:
    cfg = settings()
    since = mail.months_ago(datetime.now(ZoneInfo(cfg.timezone)).date(), cfg.mail_index_months)
    alive = set()
    indexed = skipped = skipped_attachments = 0
    async with aclosing(mail.documents(since)) as documents:
        async for doc in documents:
            n = await store.upsert_document(
                doc.id, "mail", doc.title, doc.text, modified_at=doc.modified_at
            )
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

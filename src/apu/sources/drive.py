"""Indeksiranje punog teksta sa Drive-a, uz paginaciju i bezbedno čišćenje."""

from apu.rag import store
from apu.rag.dates import timestamp
from apu.services import google


async def reindex() -> dict:
    alive = set()
    indexed = skipped = 0
    async with google.Drive() as drive:
        async for meta in drive.files():
            if not google.indexable(meta):
                continue
            doc_id = f"drive:{meta['id']}"
            if doc_id in alive:
                continue
            result = await drive.read(meta["id"], meta)
            n = await store.upsert_document(
                doc_id,
                "drive",
                result["name"],
                f"{result['name']}\n{result['content']}",
                meta.get("webViewLink"),
                modified_at=timestamp(meta.get("modifiedTime")),
            )
            alive.add(doc_id)
            indexed += bool(n)
            skipped += not n
    removed = await store.remove_missing("drive", alive)
    return {
        "indeksirano": indexed,
        "preskoceno": skipped,
        "obrisano": removed,
        "ukupno": len(alive),
    }

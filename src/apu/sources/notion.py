"""Sve dostupne Notion stranice, bez limita prve strane rezultata."""

from apu.rag import store
from apu.services import notion


async def reindex() -> dict:
    alive = set()
    indexed = skipped = 0
    async with notion.client() as api:
        async for page in notion.search_pages(api):
            if page.get("object") != "page" or page.get("archived") or page.get("in_trash"):
                continue
            doc_id = f"notion:{page['id']}"
            if doc_id in alive:
                continue
            text = await notion.read_blocks(api, page["id"])
            title = notion.title_of(page)
            n = await store.upsert_document(
                doc_id, "notion", title, f"{title}\n{text}", page.get("url")
            )
            alive.add(doc_id)
            indexed += bool(n)
            skipped += not n
    # Ne brišemo ništa ako je pretraga ili čitanje makar jedne stranice prekinuto.
    removed = await store.remove_missing("notion", alive)
    return {
        "indeksirano": indexed,
        "preskoceno": skipped,
        "obrisano": removed,
        "ukupno": len(alive),
    }

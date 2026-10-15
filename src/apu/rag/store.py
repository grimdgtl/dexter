"""Indeks i hybrid pretraga nad pgvector + PostgreSQL full-text.

Zašto hybrid: vektorska pretraga hvata ZNAČENJE ("kad me mogu otpustiti" →
član o prestanku radnog odnosa), ali promaši tačne pojmove — broj fakture,
PIB, ime klijenta, "Član 179". Full-text pretraga je obrnuto. Pustimo obe i
spojimo rezultate sa Reciprocal Rank Fusion (RRF):

    ocena(d) = Σ 1 / (k + rang_d_u_listi)

RRF ne mora da poredi ocene različitih skala (kosinus vs ts_rank), gleda
samo mesto u svakoj listi. k=60 je standardna vrednost iz literature.
"""

import hashlib
import logging
from dataclasses import dataclass

from apu.db import pool
from apu.rag.chunking import chunk_text
from apu.rag.embed import embed, embed_one

log = logging.getLogger(__name__)

RRF_K = 60
CANDIDATES = 30  # koliko kandidata uzimamo iz svake pretrage pre spajanja


@dataclass
class Hit:
    chunk_id: int
    document_id: str
    title: str
    url: str | None
    text: str
    score: float
    vector_rank: int | None = None
    keyword_rank: int | None = None


def rrf(*rankings: list[int], k: int = RRF_K) -> dict[int, float]:
    """Spaja više rangiranih lista id-jeva u jednu ocenu po id-ju."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return scores


async def upsert_document(
    doc_id: str, source: str, title: str, text: str, url: str | None = None
) -> int:
    """Indeksira dokument. Ako se sadržaj nije promenio, preskače ga (0 novih delova)."""
    content_hash = hashlib.sha256(f"{title}\n{text}".encode()).hexdigest()
    db = pool()

    existing = await db.fetchval("SELECT content_hash FROM documents WHERE id = $1", doc_id)
    if existing == content_hash:
        return 0

    chunks = chunk_text(text, title=title)
    vectors = await embed(chunks, kind="passage")

    async with db.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM documents WHERE id = $1", doc_id)  # kaskadno briše delove
        await conn.execute(
            "INSERT INTO documents (id, source, title, url, content_hash) VALUES ($1,$2,$3,$4,$5)",
            doc_id, source, title, url, content_hash,
        )  # fmt: skip
        await conn.executemany(
            "INSERT INTO chunks (document_id, ord, text, embedding) VALUES ($1, $2, $3, $4)",
            [(doc_id, i, c, v) for i, (c, v) in enumerate(zip(chunks, vectors, strict=True))],
        )
    log.info("Indeksirano %s: %d delova.", doc_id, len(chunks))
    return len(chunks)


async def remove_missing(source: str, alive_ids: set[str]) -> int:
    """Briše iz indeksa dokumente nekog izvora kojih više nema."""
    rows = await pool().fetch("SELECT id FROM documents WHERE source = $1", source)
    dead = [r["id"] for r in rows if r["id"] not in alive_ids]
    if dead:
        await pool().execute("DELETE FROM documents WHERE id = ANY($1)", dead)
    return len(dead)


async def search(query: str, limit: int = 6, source: str | None = None) -> list[Hit]:
    db = pool()
    qvec = await embed_one(query, kind="query")

    vector_rows = await db.fetch(
        """SELECT c.id FROM chunks c JOIN documents d ON d.id = c.document_id
           WHERE ($3::text IS NULL OR d.source = $3)
           ORDER BY c.embedding <=> $1 LIMIT $2""",
        qvec, CANDIDATES, source,
    )  # fmt: skip
    # websearch_to_tsquery razume i navodnike i OR, a ne puca na čudne znakove.
    keyword_rows = await db.fetch(
        """SELECT c.id FROM chunks c JOIN documents d ON d.id = c.document_id
           WHERE c.tsv @@ websearch_to_tsquery('simple', $1)
             AND ($3::text IS NULL OR d.source = $3)
           ORDER BY ts_rank(c.tsv, websearch_to_tsquery('simple', $1)) DESC LIMIT $2""",
        query, CANDIDATES, source,
    )  # fmt: skip

    vec_ids = [r["id"] for r in vector_rows]
    kw_ids = [r["id"] for r in keyword_rows]
    scores = rrf(vec_ids, kw_ids)
    top = sorted(scores, key=scores.__getitem__, reverse=True)[:limit]
    if not top:
        return []

    rows = await db.fetch(
        """SELECT c.id, c.document_id, c.text, d.title, d.url
           FROM chunks c JOIN documents d ON d.id = c.document_id WHERE c.id = ANY($1)""",
        top,
    )
    by_id = {r["id"]: r for r in rows}
    return [
        Hit(
            chunk_id=cid,
            document_id=by_id[cid]["document_id"],
            title=by_id[cid]["title"],
            url=by_id[cid]["url"],
            text=by_id[cid]["text"],
            score=round(scores[cid], 5),
            vector_rank=vec_ids.index(cid) + 1 if cid in vec_ids else None,
            keyword_rank=kw_ids.index(cid) + 1 if cid in kw_ids else None,
        )
        for cid in top
    ]

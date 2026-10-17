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
from datetime import date, datetime

from apu.config import settings
from apu.db import pool
from apu.rag.chunking import chunk_text
from apu.rag.dates import period_bounds, timestamp
from apu.rag.embed import embed, embed_one, index_fingerprint

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
    similarity: float | None = None
    modified_at: datetime | None = None


def rrf(*rankings: list[int], k: int = RRF_K) -> dict[int, float]:
    """Spaja više rangiranih lista id-jeva u jednu ocenu po id-ju."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return scores


async def upsert_document(
    doc_id: str,
    source: str,
    title: str,
    text: str,
    url: str | None = None,
    *,
    modified_at: datetime | None = None,
) -> int:
    """Indeksira dokument. Ako se sadržaj nije promenio, preskače ga (0 novih delova)."""
    content_hash = hashlib.sha256(f"{title}\n{text}".encode()).hexdigest()
    modified_at = timestamp(modified_at)
    db = pool()

    fingerprint = index_fingerprint()
    existing = await db.fetchrow("SELECT * FROM documents WHERE id = $1", doc_id)
    if (
        existing
        and existing["content_hash"] == content_hash
        and existing["index_fingerprint"] == fingerprint
    ):
        await db.execute(
            """UPDATE documents SET source=$2, url=$3,
               modified_at=COALESCE($4, modified_at) WHERE id=$1""",
            doc_id,
            source,
            url,
            modified_at,
        )
        return 0

    chunks = chunk_text(text, title=title)
    vectors = await embed(chunks, kind="passage")

    async with db.acquire() as conn, conn.transaction():
        await conn.execute(
            """INSERT INTO documents
               (id, source, title, url, content_hash, content_text, index_fingerprint, modified_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
               ON CONFLICT (id) DO UPDATE SET
                 source=EXCLUDED.source, title=EXCLUDED.title, url=EXCLUDED.url,
                 content_hash=EXCLUDED.content_hash, content_text=EXCLUDED.content_text,
                 index_fingerprint=EXCLUDED.index_fingerprint, indexed_at=now(),
                 modified_at=COALESCE(EXCLUDED.modified_at, documents.modified_at)""",
            doc_id, source, title, url, content_hash, text, fingerprint, modified_at,
        )  # fmt: skip
        await conn.execute("DELETE FROM chunks WHERE document_id = $1", doc_id)
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


async def search(
    query: str,
    limit: int = 6,
    source: str | None = None,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[Hit]:
    lower, upper = period_bounds(date_from, date_to)
    if limit < 1:
        raise ValueError("Limit mora biti pozitivan.")
    db = pool()
    qvec = await embed_one(query, kind="query")

    vector_rows = await db.fetch(
        """SELECT c.id, 1 - (c.embedding <=> $1) AS similarity
           FROM chunks c JOIN documents d ON d.id = c.document_id
           WHERE ($3::text IS NULL OR d.source = $3)
             AND ($4::timestamptz IS NULL OR d.modified_at >= $4)
             AND ($5::timestamptz IS NULL OR d.modified_at < $5)
           ORDER BY c.embedding <=> $1 LIMIT $2""",
        qvec, CANDIDATES, source, lower, upper,
    )  # fmt: skip
    # websearch_to_tsquery razume i navodnike i OR, a ne puca na čudne znakove.
    keyword_rows = await db.fetch(
        """SELECT c.id FROM chunks c JOIN documents d ON d.id = c.document_id
           WHERE c.tsv @@ websearch_to_tsquery('simple', $1)
             AND ($3::text IS NULL OR d.source = $3)
             AND ($4::timestamptz IS NULL OR d.modified_at >= $4)
             AND ($5::timestamptz IS NULL OR d.modified_at < $5)
           ORDER BY ts_rank(c.tsv, websearch_to_tsquery('simple', $1)) DESC LIMIT $2""",
        query, CANDIDATES, source, lower, upper,
    )  # fmt: skip

    vec_ids = [r["id"] for r in vector_rows]
    kw_ids = [r["id"] for r in keyword_rows]
    similarities = {r["id"]: r["similarity"] for r in vector_rows}
    scores = rrf(vec_ids, kw_ids)
    # RRF rang nije mera relevantnosti: slab vektor bez tačnog pogotka ne vraćamo.
    scores = {
        cid: score
        for cid, score in scores.items()
        if cid in kw_ids
        or (
            similarities.get(cid) is not None and similarities[cid] >= settings().rag_min_similarity
        )
    }
    top = sorted(scores, key=scores.__getitem__, reverse=True)[
        : 20 if settings().rerank == "on" else limit
    ]
    if not top:
        return []

    rows = await db.fetch(
        """SELECT c.id, c.document_id, c.text, d.title, d.url, d.modified_at
           FROM chunks c JOIN documents d ON d.id = c.document_id WHERE c.id = ANY($1)""",
        top,
    )
    by_id = {r["id"]: r for r in rows}
    hits = [
        Hit(
            chunk_id=cid,
            document_id=by_id[cid]["document_id"],
            title=by_id[cid]["title"],
            url=by_id[cid]["url"],
            text=by_id[cid]["text"],
            score=round(scores[cid], 5),
            vector_rank=vec_ids.index(cid) + 1 if cid in vec_ids else None,
            keyword_rank=kw_ids.index(cid) + 1 if cid in kw_ids else None,
            similarity=similarities.get(cid),
            modified_at=by_id[cid]["modified_at"],
        )
        for cid in top
    ]
    if settings().rerank == "on":
        from apu.rag.rerank import rerank

        hits = await rerank(query, hits)
    return hits[:limit]

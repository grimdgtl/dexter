"""Atomska promena vektorskog prostora iz sačuvanih delova i činjenica; bot mora biti ugašen."""

import argparse
import asyncio
import math

from dexter import db
from dexter.config import settings
from dexter.pismo import u_latinicu
from dexter.rag import embed as embeddings


async def reembed(conn) -> dict:
    cfg = settings()
    dim = cfg.embed_dim
    counts = {}
    async with conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(27182026)")
        await conn.execute("SET LOCAL lock_timeout = '5s'")
        await conn.execute("LOCK TABLE documents, chunks, facts IN ACCESS EXCLUSIVE MODE")
        for table in ("chunks", "facts"):
            # Privremene kolone čuvaju stare vektore sve dok svaki novi ne bude spreman.
            await conn.execute(
                f"CREATE TEMP TABLE reembed_{table} (id bigint PRIMARY KEY, embedding vector({dim})) ON COMMIT DROP"
            )
            count = 0
            batch = []

            async def save(rows, table=table):
                vectors = await embeddings.embed([r["text"] for r in rows], kind="passage")
                if len(vectors) != len(rows) or any(
                    len(v) != dim or not all(math.isfinite(x) for x in v) or not any(v)
                    for v in vectors
                ):
                    raise ValueError("Embedding model je vratio neispravne vektore.")
                await conn.executemany(
                    f"INSERT INTO reembed_{table} VALUES ($1,$2)",
                    [(r["id"], v) for r, v in zip(rows, vectors, strict=True)],
                )

            async for row in conn.cursor(f"SELECT id,text FROM {table} ORDER BY id", prefetch=64):
                batch.append(row)
                count += 1
                if len(batch) == 64:
                    await save(batch)
                    batch = []
            if batch:
                await save(batch)
            counts[table] = count
        for table in ("chunks", "facts"):
            await conn.execute(f"DROP INDEX IF EXISTS {table}_embedding_idx")
            await conn.execute(
                f"ALTER TABLE {table} ALTER COLUMN embedding TYPE vector({dim}) USING NULL"
            )
            await conn.execute(
                f"UPDATE {table} d SET embedding=s.embedding FROM reembed_{table} s WHERE d.id=s.id"
            )
            await conn.execute(
                f"CREATE INDEX {table}_embedding_idx ON {table} USING hnsw (embedding vector_cosine_ops)"
            )
        rows = await conn.fetch("SELECT id,index_fingerprint FROM documents")
        for row in rows:
            parts = (row["index_fingerprint"] or "").split(":")
            fingerprint = (
                embeddings.index_fingerprint(int(parts[1]), int(parts[2]))
                if len(parts) >= 3 and parts[0] in {"v2", "v3"}
                else None
            )
            await conn.execute(
                "UPDATE documents SET index_fingerprint=$2 WHERE id=$1", row["id"], fingerprint
            )
        await conn.execute(
            """INSERT INTO embedding_space (provider,model,dimensions) VALUES ($1,$2,$3)
               ON CONFLICT (singleton) DO UPDATE SET provider=EXCLUDED.provider,model=EXCLUDED.model,
               dimensions=EXCLUDED.dimensions,updated_at=now()""",
            cfg.embed_provider,
            cfg.embed_model,
            dim,
        )
    return {
        "delova": counts["chunks"],
        "činjenica": counts["facts"],
        "dimenzija": dim,
        "model": cfg.embed_model,
    }


async def main():
    try:
        pool = await db.connect(allow_embedding_mismatch=True)
        async with pool.acquire() as conn:
            result = await reembed(conn)
        print(u_latinicu(str(result)))
    finally:
        await db.close()


if __name__ == "__main__":
    argparse.ArgumentParser(
        description="Ponovo vektorizuje sve delove i činjenice; zaustavi bot pre pokretanja."
    ).parse_args()
    asyncio.run(main())

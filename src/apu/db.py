"""PostgreSQL + pgvector: jedna baza za sve što je ranije bilo u JSON fajlovima.

Stara verzija je čuvala istoriju, činjenice i indeks pretrage kao JSON na
disku. To radi za jednog korisnika, ali nema pretrage, nema upita i ceo fajl
se učitava u memoriju. Ovde je sve u tabelama:

  messages   — istorija razgovora (svaka poruka jedan red)
  pending_notes — ishodi potvrda za kontekst sledeće korisničke poruke
  facts      — dugoročna memorija, sa vektorom za pretragu po značenju
  documents  — izvori za RAG (Notion stranica, PDF, mejl...)
  chunks     — delovi dokumenata sa vektorom i full-text indeksom
  usage      — tokeni, cena i latencija svakog poziva modela
"""

import json
import logging

import asyncpg
from pgvector.asyncpg import register_vector

from apu.config import settings

log = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


def schema_sql(dim: int) -> str:
    return f"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS messages (
    id          BIGSERIAL PRIMARY KEY,
    chat_id     BIGINT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content     JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS messages_chat_idx ON messages (chat_id, id);

CREATE TABLE IF NOT EXISTS pending_notes (
    id          BIGSERIAL PRIMARY KEY,
    chat_id     BIGINT NOT NULL,
    text        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS pending_notes_chat_idx ON pending_notes (chat_id, id);

CREATE TABLE IF NOT EXISTS facts (
    id          BIGSERIAL PRIMARY KEY,
    text        TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT 'ostalo',
    source      TEXT NOT NULL DEFAULT 'korisnik',   -- korisnik | izvuceno
    embedding   vector({dim}),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS facts_embedding_idx
    ON facts USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS documents (
    id          TEXT PRIMARY KEY,                    -- npr. notion:abc, pdf:ugovor.pdf
    source      TEXT NOT NULL,
    title       TEXT NOT NULL,
    url         TEXT,
    content_hash TEXT NOT NULL,
    indexed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    id          BIGSERIAL PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ord         INT NOT NULL,
    text        TEXT NOT NULL,
    embedding   vector({dim}),
    tsv         tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED
);
CREATE INDEX IF NOT EXISTS chunks_embedding_idx
    ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING gin (tsv);

CREATE TABLE IF NOT EXISTS usage (
    id                  BIGSERIAL PRIMARY KEY,
    model               TEXT NOT NULL,
    purpose             TEXT NOT NULL,                -- chat | memory | scheduler ...
    input_tokens        INT NOT NULL,
    output_tokens       INT NOT NULL,
    cache_read_tokens   INT NOT NULL DEFAULT 0,
    cache_write_tokens  INT NOT NULL DEFAULT 0,
    cost_usd            NUMERIC(12, 6) NOT NULL,
    latency_ms          INT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


async def _init_conn(conn: asyncpg.Connection) -> None:
    await register_vector(conn)
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def connect() -> asyncpg.Pool:
    """Otvara pool i pravi šemu ako ne postoji (idempotentno)."""
    global _pool
    if _pool is not None:
        return _pool

    cfg = settings()
    # Ekstenzija mora da postoji PRE nego što se registruje vector tip.
    bootstrap = await asyncpg.connect(cfg.database_url)
    try:
        await bootstrap.execute(schema_sql(cfg.embed_dim))
    finally:
        await bootstrap.close()

    _pool = await asyncpg.create_pool(cfg.database_url, init=_init_conn, min_size=1, max_size=5)
    log.info("Baza spremna (embed dim %s).", cfg.embed_dim)
    return _pool


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Baza nije povezana — pozovi db.connect() pri startu.")
    return _pool

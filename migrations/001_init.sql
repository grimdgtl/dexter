CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS messages (
    id          BIGSERIAL PRIMARY KEY,
    chat_id     BIGINT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content     JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS messages_chat_idx ON messages (chat_id, id);

CREATE TABLE IF NOT EXISTS facts (
    id          BIGSERIAL PRIMARY KEY,
    text        TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT 'ostalo',
    source      TEXT NOT NULL DEFAULT 'korisnik',   -- korisnik | izvuceno
    embedding   vector({{EMBED_DIM}}),
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
    embedding   vector({{EMBED_DIM}}),
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

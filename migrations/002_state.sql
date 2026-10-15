CREATE TABLE IF NOT EXISTS pending_notes (
    id          BIGSERIAL PRIMARY KEY,
    chat_id     BIGINT NOT NULL,
    text        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS pending_notes_chat_idx ON pending_notes (chat_id, id);

CREATE TABLE IF NOT EXISTS kv_state (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

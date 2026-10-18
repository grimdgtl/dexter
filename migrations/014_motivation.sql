CREATE TABLE motivation_messages (
    id BIGSERIAL PRIMARY KEY,
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivery_key TEXT UNIQUE,
    status TEXT NOT NULL DEFAULT 'sent' CHECK (status IN ('prepared','sent','unknown'))
);

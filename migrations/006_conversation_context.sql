-- Granica sažetog prefiksa sprečava ponovnu obradu istih razmena.
CREATE TABLE conversation_context (
    chat_id BIGINT PRIMARY KEY,
    summary TEXT NOT NULL,
    through_id BIGINT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

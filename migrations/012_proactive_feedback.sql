CREATE TABLE proactive_feedback (
    kind TEXT NOT NULL CHECK (kind IN ('daily','weekly','commitment')),
    source_id BIGINT NOT NULL,
    rating SMALLINT NOT NULL CHECK (rating IN (-1,1)),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (kind,source_id)
);
ALTER TABLE commitments ADD COLUMN reminder_message_id BIGINT;
ALTER TABLE commitments ADD COLUMN reminder_text TEXT;

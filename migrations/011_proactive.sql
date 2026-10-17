CREATE TABLE proactive_runs (
    id BIGSERIAL PRIMARY KEY,
    kind TEXT NOT NULL,
    local_date DATE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status TEXT NOT NULL,
    context JSONB NOT NULL DEFAULT '{}',
    decision JSONB,
    error TEXT,
    sent_at TIMESTAMPTZ,
    telegram_message_id BIGINT
);
CREATE INDEX proactive_runs_day_idx ON proactive_runs (kind,local_date);
CREATE TABLE proactive_deliveries (
    kind TEXT NOT NULL,
    local_date DATE NOT NULL,
    run_id BIGINT NOT NULL REFERENCES proactive_runs(id),
    claimed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (kind,local_date)
);

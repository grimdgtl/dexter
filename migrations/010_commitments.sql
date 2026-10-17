CREATE TABLE commitments (
    id BIGSERIAL PRIMARY KEY,
    tekst TEXT NOT NULL,
    osoba TEXT,
    rok DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done')),
    dokaz TEXT NOT NULL,
    fingerprint TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    done_at TIMESTAMPTZ,
    reminder_claimed_at TIMESTAMPTZ,
    reminder_sent_at TIMESTAMPTZ,
    reminder_error TEXT
);
CREATE INDEX commitments_due_idx ON commitments (rok) WHERE status = 'open';

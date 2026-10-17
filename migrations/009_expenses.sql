CREATE TABLE expenses (
    id BIGSERIAL PRIMARY KEY,
    seller TEXT NOT NULL,
    tax_id TEXT CHECK (tax_id IS NULL OR tax_id ~ '^[0-9]{9}$'),
    issued_on DATE NOT NULL,
    total NUMERIC(14,2) NOT NULL CHECK (total > 0),
    vat NUMERIC(14,2) CHECK (vat >= 0 AND vat <= total),
    currency TEXT CHECK (currency IS NULL OR currency ~ '^[A-Z]{3}$'),
    items JSONB NOT NULL,
    source_sha256 TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX expenses_date_idx ON expenses (issued_on);

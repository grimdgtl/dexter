CREATE TABLE job_runs (
    id BIGSERIAL PRIMARY KEY,
    ime TEXT NOT NULL,
    start TIMESTAMPTZ NOT NULL DEFAULT now(),
    kraj TIMESTAMPTZ,
    ok BOOLEAN,
    greska TEXT,
    pokusaja INT NOT NULL DEFAULT 0
);
CREATE INDEX job_runs_start_idx ON job_runs (start DESC);

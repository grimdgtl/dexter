CREATE TABLE birthday_greetings (
    greeted_on DATE NOT NULL,
    person_id TEXT NOT NULL,
    person_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (greeted_on, person_id)
);

CREATE TABLE monitor_checks (
    id BIGSERIAL PRIMARY KEY,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    ok BOOLEAN NOT NULL,
    slow BOOLEAN NOT NULL DEFAULT false,
    status INTEGER,
    ms INTEGER NOT NULL CHECK (ms >= 0),
    error TEXT
);
CREATE INDEX monitor_checks_time_idx ON monitor_checks (checked_at, id);

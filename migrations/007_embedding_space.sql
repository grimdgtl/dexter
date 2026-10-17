-- Sama dimenzija ne dokazuje da svi vektori pripadaju istom modelu.
CREATE TABLE embedding_space (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    dimensions INTEGER NOT NULL CHECK (dimensions > 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

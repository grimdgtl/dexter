-- Vreme izvora je odvojeno od vremena indeksiranja; nepoznati stari datumi ostaju NULL.
ALTER TABLE documents ADD COLUMN modified_at TIMESTAMPTZ;
CREATE INDEX documents_modified_at_idx ON documents (modified_at);

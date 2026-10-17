-- Izvorni tekst omogućava promenu seckanja bez ponovnog preuzimanja privatnih izvora.
ALTER TABLE documents ADD COLUMN content_text TEXT;
ALTER TABLE documents ADD COLUMN index_fingerprint TEXT;

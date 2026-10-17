-- Vremensko poklapanje nije pouzdana veza pri paralelnim pozivima i sažimanju.
ALTER TABLE messages ADD COLUMN turn_id uuid;
ALTER TABLE usage ADD COLUMN turn_id uuid;
CREATE INDEX messages_turn_idx ON messages (chat_id, turn_id) WHERE turn_id IS NOT NULL;
CREATE INDEX usage_turn_idx ON usage (turn_id) WHERE turn_id IS NOT NULL;

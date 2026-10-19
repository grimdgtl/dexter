-- Potvrđeni ugovorni podsetnik može imati tačan dan, nezavisan od dana obaveze.
ALTER TABLE commitments ADD COLUMN remind_on DATE;

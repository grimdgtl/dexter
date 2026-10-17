"""Izvoz kandidata za ručnu anotaciju; potrošnja nije potvrda težine poruke."""

import argparse
import asyncio
import json
from pathlib import Path

from apu import db
from apu.agent.history import is_user_turn
from apu.config import settings
from apu.sources.conversations import message_text


async def export_rows() -> list[dict]:
    cfg = settings()
    levels = {cfg.model_fast: "lako", cfg.model_main: "srednje", cfg.model_deep: "teško"}
    rows = await db.pool().fetch(
        """SELECT m.role, m.content, m.turn_id, u.models FROM messages m
           JOIN (SELECT turn_id, array_agg(DISTINCT model ORDER BY model) AS models
                 FROM usage WHERE turn_id IS NOT NULL AND purpose = 'chat'
                 GROUP BY turn_id) u ON u.turn_id = m.turn_id
           WHERE m.chat_id = $1 AND m.role = 'user' ORDER BY m.id""",
        cfg.telegram_owner_chat_id,
    )
    out, seen = [], set()
    for row in rows:
        if row["turn_id"] in seen or not is_user_turn(dict(row)):
            continue
        seen.add(row["turn_id"])
        content = row["content"]
        # Tekstualni model ne može naučiti odluku koja zavisi od same slike.
        if isinstance(content, list) and any(b.get("type") == "image" for b in content):
            continue
        text = message_text(content).strip()
        if not text:
            continue
        predictions = {levels[m] for m in row["models"] if m in levels}
        out.append(
            {
                "poruka": text,
                "nivo": None,
                "predlog_nivoa": next(iter(predictions)) if len(predictions) == 1 else None,
                "modeli": row["models"],
                "razmena": str(row["turn_id"]),
            }
        )
    return out


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Ponovljen izvoz ne sme prepisati ručno unete oznake.
    with path.open("x") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


async def main(output):
    try:
        await db.connect()
        rows = await export_rows()
        await asyncio.to_thread(write_rows, output, rows)
        print(f"Izvezeno {len(rows)} poruka. Ručno popuni nivo: lako, srednje ili teško.")
    finally:
        await db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Privatni skup iz povezane istorije i potrošnje.")
    parser.add_argument("--output", type=Path, default=Path("data/router-candidates.jsonl"))
    asyncio.run(main(parser.parse_args().output))

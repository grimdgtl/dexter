"""Ponovno seckanje svih sačuvanih tekstova, bez mrežnog čitanja izvora."""

import argparse
import asyncio
from datetime import date

from dexter import db
from dexter.pismo import u_latinicu
from dexter.rag import store
from dexter.rag.dates import day_start


async def reindex_all(source: str | None = None) -> dict:
    rows = await db.pool().fetch(
        "SELECT * FROM documents WHERE ($1::text IS NULL OR source = $1) ORDER BY id", source
    )
    missing = [r["id"] for r in rows if r["content_text"] is None]
    if missing:
        raise ValueError(
            "Nedostaje izvorni tekst starih dokumenata: "
            + ", ".join(missing)
            + ". Prvo osveži njihove izvore preko knowledge_reindex, odnosno ponovo uvezi fajlove."
        )
    indexed = skipped = chunks = 0
    for row in rows:
        modified_at = row["modified_at"]
        if (
            modified_at is None
            and row["source"] == "razgovor"
            and row["id"].startswith("razgovor:")
        ):
            modified_at = day_start(date.fromisoformat(row["id"].split(":", 1)[1]))
        count = await store.upsert_document(
            row["id"],
            row["source"],
            row["title"],
            row["content_text"],
            row["url"],
            modified_at=modified_at,
        )
        indexed += bool(count)
        skipped += not count
        chunks += count
    return {"ukupno": len(rows), "indeksirano": indexed, "preskoceno": skipped, "delova": chunks}


async def run(source: str | None = None) -> dict:
    try:
        await db.connect()
        return await reindex_all(source)
    finally:
        await db.close()


def cli(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Ponovo secka sve sačuvane dokumente.")
    parser.add_argument("--izvor")
    args = parser.parse_args(argv)
    try:
        print(u_latinicu(str(asyncio.run(run(args.izvor)))))
    except ValueError as exc:
        parser.error(u_latinicu(str(exc)))


if __name__ == "__main__":
    cli()

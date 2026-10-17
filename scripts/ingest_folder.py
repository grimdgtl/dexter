"""Uvoz PDF/txt/md foldera; sadržaj ostaje u Postgres indeksu, ne u git-u."""

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path

from apu import db
from apu.pismo import u_latinicu
from apu.rag.ingest import ingest_file


async def ingest_folder(folder: Path, source: str = "zakon") -> list[dict]:
    folder = folder.resolve()
    if not folder.is_dir():
        raise ValueError("Putanja mora biti postojeći folder.")
    if not source.strip():
        raise ValueError("Izvor ne sme biti prazan.")

    def find_files():
        return sorted(
            p
            for p in folder.rglob("*")
            if p.is_file() and not p.is_symlink() and p.suffix.lower() in {".pdf", ".txt", ".md"}
        )

    results = []
    for path in await asyncio.to_thread(find_files):
        name = path.relative_to(folder).as_posix()
        try:
            data = await asyncio.to_thread(path.read_bytes)
            stat = await asyncio.to_thread(path.stat)
            count, message = await ingest_file(
                name, data, source=source, modified_at=datetime.fromtimestamp(stat.st_mtime, UTC)
            )
            results.append({"fajl": name, "delova": count, "poruka": message, "ok": True})
        except Exception as exc:
            results.append({"fajl": name, "delova": 0, "poruka": u_latinicu(str(exc)), "ok": False})
    return results


async def run(folder: Path, source: str) -> int:
    if not folder.is_dir():
        raise ValueError("Putanja mora biti postojeći folder.")
    try:
        await db.connect()
        results = await ingest_folder(folder, source)
        for row in results:
            status = "OK" if row["ok"] else "GREŠKA"
            print(u_latinicu(f"{status} {row['fajl']}: {row['poruka']}"))
        print(f"Fajlova: {len(results)}, novih delova: {sum(r['delova'] for r in results)}")
        return int(any(not row["ok"] for row in results))
    finally:
        await db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Indeksira PDF/txt/md fajlove iz foldera i podfoldera."
    )
    parser.add_argument("putanja", type=Path)
    parser.add_argument("--izvor", default="zakon")
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(run(args.putanja, args.izvor)))
    except ValueError as exc:
        parser.error(u_latinicu(str(exc)))

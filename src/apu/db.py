"""PostgreSQL + pgvector: jedna baza za sve što je ranije bilo u JSON fajlovima.

Stara verzija je čuvala istoriju, činjenice i indeks pretrage kao JSON na
disku. To radi za jednog korisnika, ali nema pretrage, nema upita i ceo fajl
se učitava u memoriju. Ovde je sve u tabelama:

  messages   — istorija razgovora (svaka poruka jedan red)
  pending_notes — ishodi potvrda za kontekst sledeće korisničke poruke
  facts      — dugoročna memorija, sa vektorom za pretragu po značenju
  documents  — izvori za RAG (Notion stranica, PDF, mejl...)
  chunks     — delovi dokumenata sa vektorom i full-text indeksom
  usage      — tokeni, cena i latencija svakog poziva modela
"""

import asyncio
import json
import logging
from pathlib import Path

import asyncpg
from pgvector.asyncpg import register_vector

from apu.config import settings

log = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


MIGRATIONS_DIR = Path(__file__).with_name("migrations")
if not MIGRATIONS_DIR.is_dir():
    MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


async def migrate(conn: asyncpg.Connection, dim: int, directory: Path | None = None) -> list[str]:
    """Primenjuje neizvršene migracije zajedno, da neuspeh ne ostavi pola šeme."""
    if not isinstance(dim, int) or dim <= 0:
        raise ValueError("Dimenzija vektora mora biti pozitivan ceo broj.")
    paths = sorted((directory or MIGRATIONS_DIR).glob("[0-9][0-9][0-9]_*.sql"))
    versions = [p.name.split("_", 1)[0] for p in paths]
    if not paths or len(versions) != len(set(versions)):
        raise ValueError("Migracije nedostaju ili imaju ponovljen broj.")
    applied = []
    async with conn.transaction():
        # Paralelni startovi ne smeju istovremeno da menjaju šemu.
        await conn.execute("SELECT pg_advisory_xact_lock(27182026)")
        await conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        existing = {r["version"] for r in await conn.fetch("SELECT version FROM schema_migrations")}
        for version, path in zip(versions, paths, strict=True):
            if version in existing:
                continue
            sql = await asyncio.to_thread(path.read_text, encoding="utf-8")
            await conn.execute(sql.replace("{{EMBED_DIM}}", str(dim)))
            await conn.execute("INSERT INTO schema_migrations (version) VALUES ($1)", version)
            applied.append(version)
    return applied


async def _init_conn(conn: asyncpg.Connection) -> None:
    await register_vector(conn)
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def connect() -> asyncpg.Pool:
    """Otvara pool i primenjuje nove migracije."""
    global _pool
    if _pool is not None:
        return _pool

    cfg = settings()
    # Ekstenzija mora da postoji PRE nego što se registruje vector tip.
    bootstrap = await asyncpg.connect(cfg.database_url)
    try:
        await migrate(bootstrap, cfg.embed_dim)
    finally:
        await bootstrap.close()

    _pool = await asyncpg.create_pool(cfg.database_url, init=_init_conn, min_size=1, max_size=5)
    log.info("Baza spremna (embed dim %s).", cfg.embed_dim)
    return _pool


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Baza nije povezana — pozovi db.connect() pri startu.")
    return _pool

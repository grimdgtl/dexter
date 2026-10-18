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

from dexter.config import settings

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


async def check_embedding_space(conn, *, allow_mismatch=False):
    cfg = settings()
    async with conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(27182026)")
        dims = [
            await conn.fetchval(
                "SELECT atttypmod FROM pg_attribute WHERE attrelid=$1::regclass AND attname='embedding'",
                table,
            )
            for table in ("chunks", "facts")
        ]
        if len(set(dims)) != 1:
            raise RuntimeError(
                "Vektorske kolone imaju različite dimenzije; potrebna je obnova indeksa."
            )
        state = await conn.fetchrow("SELECT * FROM embedding_space WHERE singleton")
        if state is None:
            populated = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM chunks UNION ALL SELECT 1 FROM facts)"
            )
            legacy = {
                1536: ("openai", "text-embedding-3-small"),
                384: ("local", "intfloat/multilingual-e5-small"),
            }
            provider, model = (
                legacy.get(dims[0], ("unknown", "unknown"))
                if populated
                else (cfg.embed_provider, cfg.embed_model)
            )
            await conn.execute(
                "INSERT INTO embedding_space (provider,model,dimensions) VALUES ($1,$2,$3)",
                provider,
                model,
                dims[0],
            )
            state = {"provider": provider, "model": model, "dimensions": dims[0]}
        expected = (cfg.embed_provider, cfg.embed_model, cfg.embed_dim)
        current = (state["provider"], state["model"], state["dimensions"])
        if not allow_mismatch and (current != expected or dims[0] != cfg.embed_dim):
            raise RuntimeError(
                "Embedding model/dimenzija ne odgovara bazi. Zaustavi bot i pokreni python -m scripts.reembed."
            )


async def connect(*, allow_embedding_mismatch: bool = False) -> asyncpg.Pool:
    """Otvara pool i primenjuje nove migracije."""
    global _pool
    if _pool is not None:
        return _pool

    cfg = settings()
    # Ekstenzija mora da postoji PRE nego što se registruje vector tip.
    bootstrap = await asyncpg.connect(cfg.database_url)
    try:
        await migrate(bootstrap, cfg.embed_dim)
        await check_embedding_space(bootstrap, allow_mismatch=allow_embedding_mismatch)
    finally:
        await bootstrap.close()

    _pool = await asyncpg.create_pool(cfg.database_url, init=_init_conn, min_size=1, max_size=5)
    log.info("Baza spremna (embed dim %s).", cfg.embed_dim)
    return _pool


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Baza nije povezana — pozovi db.connect() pri startu.")
    return _pool


async def close() -> None:
    global _pool
    current, _pool = _pool, None
    if current is not None:
        await current.close()

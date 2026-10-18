"""Embeddinzi: tekst → vektor. Dva provajdera, isti interfejs.

  openai — text-embedding-3-small preko API-ja (1536 dim). Jeftino, bez servera.
  local  — intfloat/multilingual-e5-small sa Hugging Face-a (384 dim), radi na
           Hetzneru bez API ključa. Traži `pip install ".[local]"`.

Faza 4 plana: isti eval set pusti kroz oba i uporedi kvalitet i cenu.

E5 modeli traže prefiks "query: " za pitanja i "passage: " za dokumente —
bez toga kvalitet pretrage primetno pada. Zato `embed` zna da li vektorizuje
upit ili dokument.
"""

import asyncio
import logging
import math
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from typing import Literal

import httpx

from dexter.config import settings

log = logging.getLogger(__name__)

Kind = Literal["query", "passage"]
OPENAI_MODEL = "text-embedding-3-small"
BATCH = 64
_local_lock = threading.Lock()
_measurements: ContextVar[list | None] = ContextVar("embedding_measurements", default=None)


@contextmanager
def measure():
    rows = []
    token = _measurements.set(rows)
    try:
        yield rows
    finally:
        _measurements.reset(token)


def index_fingerprint(size: int | None = None, overlap: int | None = None) -> str:
    cfg = settings()
    size = cfg.chunk_chars if size is None else size
    overlap = cfg.chunk_overlap if overlap is None else overlap
    return f"v3:{size}:{overlap}:{cfg.embed_provider}:{cfg.embed_model}:{cfg.embed_dim}"


async def _openai(texts: list[str]) -> list[list[float]]:
    key = settings().openai_api_key
    if not key:
        raise RuntimeError("EMBED_PROVIDER=openai traži OPENAI_API_KEY.")
    out: list[list[float]] = []
    async with httpx.AsyncClient(timeout=60) as client:
        for i in range(0, len(texts), BATCH):
            r = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": OPENAI_MODEL, "input": texts[i : i + BATCH]},
            )
            r.raise_for_status()
            payload = r.json()
            data = sorted(payload["data"], key=lambda x: x["index"])
            if [x["index"] for x in data] != list(range(len(texts[i : i + BATCH]))):
                raise ValueError("Embedding API nije vratio sve indekse po jednom.")
            out.extend(x["embedding"] for x in data)
            rows = _measurements.get()
            if rows is not None:
                rows.append({"api_tokens": payload.get("usage", {}).get("total_tokens")})
    return out


@lru_cache(maxsize=1)
def _local_model(name: str):
    from sentence_transformers import SentenceTransformer  # teški import, samo kad treba

    log.info("Učitavam lokalni embedding model %s…", name)
    return SentenceTransformer(name, device="cpu", trust_remote_code=False)


def _local_sync(texts: list[str], kind: Kind) -> list[list[float]]:
    prefixed = [f"{kind}: {t}" for t in texts]
    with _local_lock:
        vecs = _local_model(settings().embed_local_model).encode(
            prefixed, batch_size=BATCH, normalize_embeddings=True, show_progress_bar=False
        )
    return [v.tolist() for v in vecs]


async def embed(texts: list[str], kind: Kind = "passage") -> list[list[float]]:
    if not texts:
        return []
    started = time.perf_counter()
    if settings().embed_provider == "local":
        # Model radi na CPU-u i blokira — guramo ga u thread da bot ne zastane.
        vectors = await asyncio.to_thread(_local_sync, texts, kind)
    else:
        vectors = await _openai(texts)
    if len(vectors) != len(texts) or any(
        len(v) != settings().embed_dim or not all(math.isfinite(x) for x in v) or not any(v)
        for v in vectors
    ):
        raise ValueError(
            "Embedding model je vratio neispravan broj, dimenziju ili vrednost vektora."
        )
    rows = _measurements.get()
    if rows is not None:
        rows.append(
            {
                "provider": settings().embed_provider,
                "model": settings().embed_model,
                "kind": kind,
                "texts": len(texts),
                "ms": 1000 * (time.perf_counter() - started),
            }
        )
    return vectors


async def embed_one(text: str, kind: Kind = "query") -> list[float]:
    return (await embed([text], kind))[0]

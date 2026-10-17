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
from functools import lru_cache
from typing import Literal

import httpx

from apu.config import settings

log = logging.getLogger(__name__)

Kind = Literal["query", "passage"]
OPENAI_MODEL = "text-embedding-3-small"
LOCAL_MODEL = "intfloat/multilingual-e5-small"
BATCH = 64


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
            out.extend(x["embedding"] for x in r.json()["data"])
    return out


@lru_cache
def _local_model():
    from sentence_transformers import SentenceTransformer  # teški import, samo kad treba

    log.info("Učitavam lokalni embedding model %s…", LOCAL_MODEL)
    return SentenceTransformer(LOCAL_MODEL)


def _local_sync(texts: list[str], kind: Kind) -> list[list[float]]:
    prefixed = [f"{kind}: {t}" for t in texts]
    vecs = _local_model().encode(prefixed, batch_size=BATCH, normalize_embeddings=True)
    return [v.tolist() for v in vecs]


async def embed(texts: list[str], kind: Kind = "passage") -> list[list[float]]:
    if not texts:
        return []
    if settings().embed_provider == "local":
        # Model radi na CPU-u i blokira — guramo ga u thread da bot ne zastane.
        return await asyncio.to_thread(_local_sync, texts, kind)
    return await _openai(texts)


async def embed_one(text: str, kind: Kind = "query") -> list[float]:
    return (await embed([text], kind))[0]

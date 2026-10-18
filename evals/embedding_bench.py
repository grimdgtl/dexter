"""Isti RAG korpus i upiti za OpenAI, E5 small i E5 base, samo u izdvojenoj bazi."""

import argparse
import asyncio
import hashlib
import json
import time
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

from dexter import db
from dexter.config import settings
from dexter.pismo import u_latinicu
from dexter.rag import embed as embeddings
from dexter.rag import store
from evals.rag_eval import metrics
from scripts.reembed import reembed

HERE = Path(__file__).parent
MODELS = {
    "openai": ("openai", "intfloat/multilingual-e5-small"),
    "small": ("local", "intfloat/multilingual-e5-small"),
    "base": ("local", "intfloat/multilingual-e5-base"),
}


def read_corpus(path):
    corpus = json.loads(Path(path).read_text())
    if not corpus.get("documents") or not corpus.get("questions"):
        raise ValueError("Korpus mora imati documents i questions.")
    ids = [d["id"] for d in corpus["documents"]]
    if len(set(ids)) != len(ids) or any(
        not isinstance(d.get("text"), str) or not d["text"].strip() for d in corpus["documents"]
    ):
        raise ValueError("Dokumenti moraju imati jedinstvene ID-jeve i tekst.")
    if any(
        not q.get("pitanje") or (q.get("dokument") is not None and q["dokument"] not in ids)
        for q in corpus["questions"]
    ):
        raise ValueError("Pitanja moraju upućivati na dokument korpusa ili null.")
    return corpus


async def benchmark(corpus, models, *, price_per_million=None):
    name = await db.pool().fetchval("SELECT current_database()")
    if not name.endswith(("_test", "_bench")):
        raise ValueError("Koristi izdvojenu _test ili _bench bazu.")
    if await db.pool().fetchval(
        "SELECT EXISTS(SELECT 1 FROM documents WHERE source != 'benchmark') OR EXISTS(SELECT 1 FROM facts)"
    ):
        raise ValueError(
            "Baza ima dokumente ili činjenice van benchmarka; koristi praznu izdvojenu bazu."
        )
    await db.pool().execute("DELETE FROM documents WHERE source='benchmark'")
    results = []
    for model in models:
        provider, local = MODELS[model]
        with (
            patch.object(settings(), "embed_provider", provider),
            patch.object(settings(), "embed_local_model", local),
            patch.object(settings(), "rerank", "off"),
        ):
            if provider == "openai" and not settings().openai_api_key:
                results.append(
                    {
                        "model": settings().embed_model,
                        "izvršeno": False,
                        "razlog": "Nema OPENAI_API_KEY.",
                    }
                )
                continue
            start = time.perf_counter()
            with embeddings.measure() as measurements:
                async with db.pool().acquire() as conn:
                    await reembed(conn)
                for doc in corpus["documents"]:
                    await store.upsert_document(doc["id"], "benchmark", doc["title"], doc["text"])
                await store.remove_missing("benchmark", set(d["id"] for d in corpus["documents"]))
                index_seconds = time.perf_counter() - start
                ranked = []
                start = time.perf_counter()
                for question in corpus["questions"]:
                    ranked.append(
                        [h.document_id for h in await store.search(question["pitanje"], limit=15)]
                    )
                ms = 1000 * (time.perf_counter() - start) / len(ranked)
            tokens = [r["api_tokens"] for r in measurements if "api_tokens" in r]
            known = all(t is not None for t in tokens)
            total = sum(tokens) if known else None
            cost = (
                0.0
                if provider == "local"
                else float(Decimal(total) * Decimal(str(price_per_million)) / 1000000)
                if total is not None and price_per_million is not None
                else None
            )
            result = metrics(ranked, [q["dokument"] for q in corpus["questions"]], 5)
            result |= {
                "model": settings().embed_model,
                "izvršeno": True,
                "dimensions": settings().embed_dim,
                "index_seconds": round(index_seconds, 3),
                "ms_po_upitu": round(ms, 2),
                "api_tokens": total,
                "api_usd": cost,
                "prag": settings().rag_min_similarity,
                "korpus_sha256": hashlib.sha256(
                    json.dumps(corpus, sort_keys=True, ensure_ascii=False).encode()
                ).hexdigest(),
            }
            results.append(result)
    return results


async def main(path, models, price):
    if not unquote(urlsplit(settings().database_url).path).endswith(("_test", "_bench")):
        raise ValueError("DATABASE_URL mora biti izdvojena _test ili _bench baza.")
    corpus = await asyncio.to_thread(read_corpus, path)
    try:
        await db.connect(allow_embedding_mismatch=True)
        results = await benchmark(corpus, models, price_per_million=price)
        print(u_latinicu(json.dumps(results, ensure_ascii=False, indent=2)))
        return results
    finally:
        await db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Poredi embedding modele na istom korpusu u izdvojenoj bazi."
    )
    parser.add_argument("--korpus", type=Path, default=HERE / "embedding.example.json")
    parser.add_argument("--modeli", nargs="+", choices=list(MODELS), default=list(MODELS))
    parser.add_argument(
        "--usd-za-milion",
        type=Decimal,
        help="Važeća API cena ulaznih tokena; bez nje USD ostaje null.",
    )
    args = parser.parse_args()
    if args.usd_za_milion is not None and (
        not args.usd_za_milion.is_finite() or args.usd_za_milion < 0
    ):
        parser.error("Cena mora biti konačna i nenegativna.")
    asyncio.run(main(args.korpus, args.modeli, args.usd_za_milion))

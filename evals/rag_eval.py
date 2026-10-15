"""Evaluacija pretrage: koliko često je tačan dokument među prvih K rezultata.

Ovo je ono što pretvara "mislim da je bolje" u "recall@5 je skočio sa 55% na 85%".

Format evals/questions.jsonl (jedno pitanje po redu, napravi ~30 sa svojim
podacima — fajl je u .gitignore jer sadrži lične stvari):

    {"pitanje": "koliki je PIB firme ABC Studio", "dokument": "notion:abc123"}
    {"pitanje": "šta piše o otkaznom roku", "dokument": "zakon:zakon-o-radu.pdf"}

Pokretanje (uz pokrenutu bazu i indeks):
    python -m evals.rag_eval --k 5 --oznaka "hybrid-1200"

Metrike:
  recall@k — udeo pitanja gde je tačan dokument u top k
  MRR      — prosek 1/mesto prvog tačnog (1.0 = uvek prvi)
Rezultat se dopisuje u evals/results/log.jsonl da možeš da porediš verzije.
"""

import argparse
import asyncio
import json
import time
from pathlib import Path

from apu import db
from apu.rag import store

HERE = Path(__file__).parent


def metrics(ranked_docs: list[list[str]], expected: list[str], k: int) -> dict:
    hits, rr = 0, 0.0
    for docs, exp in zip(ranked_docs, expected, strict=True):
        unique = list(dict.fromkeys(docs))  # više delova istog dokumenta = jedno mesto
        if exp in unique[:k]:
            hits += 1
        if exp in unique:
            rr += 1 / (unique.index(exp) + 1)
    n = max(len(expected), 1)
    return {"recall_at_k": round(hits / n, 3), "mrr": round(rr / n, 3), "n": len(expected)}


async def main(k: int, label: str) -> None:
    await db.connect()
    qs = [json.loads(line) for line in (HERE / "questions.jsonl").read_text().splitlines() if line]

    ranked, misses = [], []
    start = time.perf_counter()
    for q in qs:
        hits = await store.search(q["pitanje"], limit=k * 3)
        docs = [h.document_id for h in hits]
        ranked.append(docs)
        top_k = list(dict.fromkeys(docs))[:k]
        if q["dokument"] not in top_k:
            misses.append({"pitanje": q["pitanje"], "ocekivano": q["dokument"], "dobijeno": top_k})
    elapsed = time.perf_counter() - start

    m = metrics(ranked, [q["dokument"] for q in qs], k)
    m |= {"k": k, "oznaka": label, "ms_po_upitu": round(1000 * elapsed / max(len(qs), 1))}
    print(json.dumps(m, ensure_ascii=False, indent=2))
    for miss in misses:
        print("PROMAŠAJ:", json.dumps(miss, ensure_ascii=False))

    (HERE / "results").mkdir(exist_ok=True)
    with open(HERE / "results" / "log.jsonl", "a") as f:
        f.write(json.dumps(m, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--oznaka", default="bez-oznake")
    a = p.parse_args()
    asyncio.run(main(a.k, a.oznaka))

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
from datetime import UTC, datetime
from pathlib import Path

from apu import db
from apu.pismo import u_latinicu
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


def read_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("Zapis nije objekat.")
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Neispravan eval zapis {path.name}:{number}") from exc
        rows.append(row)
    return rows


def comparison(rows: list[dict]) -> str:
    if not rows:
        return "Nema prethodnih eval pokretanja."
    lines = [
        "Datum | Oznaka | k | recall@k | MRR | ms po upitu",
        "--- | --- | --- | --- | --- | ---",
    ]
    for row in rows:
        values = [
            row.get(key, "—")
            for key in ("datum", "oznaka", "k", "recall_at_k", "mrr", "ms_po_upitu")
        ]
        lines.append(
            " | ".join(str(value).replace("|", "/").replace("\n", " ") for value in values)
        )
    return "\n".join(lines)


def read_questions(path: Path) -> list[dict]:
    qs = read_log(path)
    if not qs:
        raise ValueError("Napravi evals/questions.jsonl sa pitanjima nad svojim podacima.")
    for i, question in enumerate(qs, 1):
        if not all(
            isinstance(question.get(key), str) and question[key].strip()
            for key in ("pitanje", "dokument")
        ):
            raise ValueError(f"Pitanje {i} mora imati tekstualna polja pitanje i dokument.")
    return qs


async def main(k: int, label: str) -> dict:
    if k < 1:
        raise ValueError("k mora biti pozitivan ceo broj.")
    qs = await asyncio.to_thread(read_questions, HERE / "questions.jsonl")
    try:
        await db.connect()
        ranked, misses = [], []
        start = time.perf_counter()
        for q in qs:
            hits = await store.search(q["pitanje"], limit=k * 3)
            docs = [h.document_id for h in hits]
            ranked.append(docs)
            top_k = list(dict.fromkeys(docs))[:k]
            if q["dokument"] not in top_k:
                misses.append(
                    {"pitanje": q["pitanje"], "ocekivano": q["dokument"], "dobijeno": top_k}
                )
        elapsed = time.perf_counter() - start
        m = metrics(ranked, [q["dokument"] for q in qs], k)
        m |= {
            "k": k,
            "oznaka": label,
            "ms_po_upitu": round(1000 * elapsed / len(qs)),
            "datum": datetime.now(UTC).isoformat(),
        }
        print(u_latinicu(json.dumps(m, ensure_ascii=False, indent=2)))
        for miss in misses:
            print("PROMAŠAJ:", u_latinicu(json.dumps(miss, ensure_ascii=False)))
        await asyncio.to_thread(append_result, m)
        return m
    finally:
        await db.close()


def append_result(result: dict) -> None:
    path = HERE / "results" / "log.jsonl"
    path.parent.mkdir(exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")


def cli(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Merenje i poređenje RAG pretrage.")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--oznaka", default="bez-oznake")
    parser.add_argument("--uporedi", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.uporedi:
            print(u_latinicu(comparison(read_log(HERE / "results" / "log.jsonl"))))
        else:
            asyncio.run(main(args.k, args.oznaka))
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    cli()

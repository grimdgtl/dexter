"""Dugoročna memorija: činjenice o korisniku, sa pretragom po značenju.

Stara verzija je ubacivala SVIH do 300 činjenica u svaki prompt. To košta
tokene i razbija keš kad god se doda nova činjenica. Ovde:

  1. Pre odgovora: `recall` nađe ~8 činjenica najrelevantnijih za poruku
     (vektorska pretraga) i one idu uz poruku — ne u system prompt.
  2. Posle odgovora: `extract_and_save` u pozadini pusti brzi model preko
     razmene da izvuče nove trajne činjenice ("Marko je knjigovođa",
     "ne voli sastanke pre 10h"). Korisnik ne mora da kaže "zapamti".
  3. Duplikati: ako nova činjenica ima kosinusnu sličnost > 0.9 sa postojećom,
     postojeća se zamenjuje novom (verovatno je ažuriranje, ne nova stvar).
"""

import json
import logging

from apu import llm
from apu.db import pool
from apu.rag.embed import embed_one

log = logging.getLogger(__name__)

CATEGORIES = ["osoba", "preferencija", "projekat", "navika", "cilj", "ostalo"]
DUPLICATE_SIMILARITY = 0.90
RECALL_MIN_SIMILARITY = 0.30


async def save(text: str, category: str = "ostalo", source: str = "korisnik") -> dict:
    text = text.strip()
    if not text:
        raise ValueError("Prazna činjenica.")
    if category not in CATEGORIES:
        category = "ostalo"

    vec = await embed_one(text, kind="passage")
    db = pool()
    dup = await db.fetchrow(
        """SELECT id, text, 1 - (embedding <=> $1) AS sim FROM facts
           ORDER BY embedding <=> $1 LIMIT 1""",
        vec,
    )
    if dup and dup["sim"] >= DUPLICATE_SIMILARITY:
        await db.execute(
            "UPDATE facts SET text=$1, category=$2, embedding=$3, updated_at=now() WHERE id=$4",
            text, category, vec, dup["id"],
        )  # fmt: skip
        return {"id": dup["id"], "azurirano": True, "prethodno": dup["text"]}

    fid = await db.fetchval(
        "INSERT INTO facts (text, category, source, embedding) VALUES ($1,$2,$3,$4) RETURNING id",
        text, category, source, vec,
    )  # fmt: skip
    return {"id": fid, "azurirano": False}


async def recall(query: str, limit: int = 8) -> list[dict]:
    vec = await embed_one(query, kind="query")
    rows = await pool().fetch(
        """SELECT id, text, category, 1 - (embedding <=> $1) AS sim FROM facts
           ORDER BY embedding <=> $1 LIMIT $2""",
        vec, limit,
    )  # fmt: skip
    return [dict(r) for r in rows if r["sim"] >= RECALL_MIN_SIMILARITY]


async def forget(fact_id: int) -> bool:
    return (await pool().execute("DELETE FROM facts WHERE id = $1", fact_id)).endswith("1")


async def list_all(category: str | None = None) -> list[dict]:
    rows = await pool().fetch(
        """SELECT id, text, category, source, updated_at FROM facts
           WHERE ($1::text IS NULL OR category = $1) ORDER BY updated_at DESC""",
        category,
    )
    return [dict(r) for r in rows]


EXTRACT_PROMPT = """Iz razmene ispod izvuci TRAJNE činjenice o korisniku koje će biti korisne \
i za nedelju ili mesec dana: ljudi i odnosi, preferencije, projekti, navike, ciljevi.

Ne izvlači: privremene stvari ("danas sam umoran"), ono što već piše u kalendaru ili \
zadacima, opšte znanje, ništa što korisnik nije zaista rekao.

Kategorije: {cats}.
Vrati ISKLJUČIVO JSON listu, npr. [{{"tekst": "...", "kategorija": "osoba"}}]. \
Ako nema ničeg trajnog, vrati [].

<razmena>
KORISNIK: {user}
APU: {assistant}
</razmena>"""


def parse_facts(raw: str) -> list[dict]:
    """Tolerantno čitanje JSON-a iz modela (ume da doda ```json ograde)."""
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [
        {"tekst": str(f["tekst"]).strip(), "kategorija": f.get("kategorija", "ostalo")}
        for f in data
        if isinstance(f, dict) and str(f.get("tekst", "")).strip()
    ]


async def extract_and_save(user_text: str, assistant_text: str) -> int:
    """Poziva se u pozadini posle svake razmene. Vraća broj sačuvanih činjenica."""
    if len(user_text) < 15:  # "ok", "hvala" — nema šta da se izvuče
        return 0
    try:
        raw = await llm.complete(
            EXTRACT_PROMPT.format(
                cats=", ".join(CATEGORIES), user=user_text[:3000], assistant=assistant_text[:2000]
            ),
            purpose="memory",
            max_tokens=600,
        )
        facts = parse_facts(raw)
        for f in facts:
            await save(f["tekst"], f["kategorija"], source="izvuceno")
        if facts:
            log.info("Memorija: izvučeno %d činjenica.", len(facts))
        return len(facts)
    except Exception:
        log.exception("Izvlačenje memorije nije uspelo.")
        return 0

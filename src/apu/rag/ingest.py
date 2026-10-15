"""Pipeline: fajl → tekst → indeks.

Za sada: PDF (tekstualni), .txt, .md. Faza 5 dodaje skenirane PDF-ove i slike
(OCR preko Claude vision), a izvori iz Notion-a, Drive-a i mejla dolaze kad se
prebace ti alati (faza 1b) — svaki izvor samo zove `upsert_document`.
"""

import asyncio
import io
from pathlib import Path

from pypdf import PdfReader

from apu.pismo import u_latinicu
from apu.rag.store import upsert_document


def pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    pages = [(p.extract_text() or "").strip() for p in reader.pages]
    return "\n\n".join(p for p in pages if p)


async def ingest_file(name: str, data: bytes, source: str = "fajl") -> tuple[int, str]:
    """Vraća (broj delova, poruka). PDF bez teksta je verovatno sken → treba OCR."""
    suffix = Path(name).suffix.lower()
    if suffix == ".pdf":
        text = await asyncio.to_thread(pdf_text, data)
    elif suffix in {".txt", ".md", ".csv"}:
        text = data.decode("utf-8-sig", errors="replace")
    else:
        return 0, f"Format {suffix} još nije podržan."

    if len(text.strip()) < 50:
        return 0, "Dokument nema čitljiv tekst (verovatno skeniran) — OCR dolazi u fazi 5."

    n = await upsert_document(
        f"{source}:{name}", source, u_latinicu(Path(name).stem), u_latinicu(text)
    )
    return n, f"Indeksirano {n} delova." if n else "Dokument je već indeksiran (bez izmena)."

"""Pipeline: fajl → tekst ili OCR → indeks."""

import asyncio
import io
from datetime import UTC, datetime
from pathlib import Path

from pypdf import PdfReader

from apu.config import settings
from apu.pismo import u_latinicu
from apu.rag import ocr, office
from apu.rag.store import upsert_document


def pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    pages = [(p.extract_text() or "").strip() for p in reader.pages]
    return "\n\n".join(p for p in pages if p)


def _pdf_pages(data: bytes) -> list[str]:
    reader = PdfReader(io.BytesIO(data))
    return [(p.extract_text() or "").strip() for p in reader.pages]


async def read_pdf(data: bytes) -> str:
    pages = await asyncio.to_thread(_pdf_pages, data)
    missing = [i for i, text in enumerate(pages) if not text.strip()]
    if len(missing) > settings().ocr_max_pages:
        raise ValueError(
            f"PDF traži OCR za {len(missing)} stranica; OCR_MAX_PAGES={settings().ocr_max_pages}. "
            "Podeli dokument na manje celine. Ništa nije indeksirano."
        )
    for i in missing:
        pages[i] = await ocr.read_page(data, i)
    return "\n\n".join(pages)


async def ingest_file(
    name: str,
    data: bytes,
    source: str = "fajl",
    *,
    modified_at: datetime | None = None,
) -> tuple[int, str]:
    """Vraća (broj delova, poruka); neuspešan OCR ne ostavlja delimičan indeks."""
    suffix = Path(name).suffix.lower()
    if suffix == ".pdf":
        text = await read_pdf(data)
    elif suffix in office.SUFFIXES:
        text = await asyncio.to_thread(office.text, name, data)
    elif suffix in {".txt", ".md", ".csv"}:
        text = data.decode("utf-8-sig", errors="replace")
    else:
        return 0, f"Format {suffix} još nije podržan."

    if len(text.strip()) < 50:
        return 0, "Dokument nema dovoljno čitljivog teksta za indeksiranje."

    n = await upsert_document(
        f"{source}:{name}",
        source,
        u_latinicu(Path(name).stem),
        u_latinicu(text),
        modified_at=modified_at or datetime.now(UTC),
    )
    return n, f"Indeksirano {n} delova." if n else "Dokument je već indeksiran (bez izmena)."

"""Pregled podešavanja i baze bez otkrivanja vrednosti tajni."""

import logging

from dexter.config import settings
from dexter.db import pool
from dexter.tools import registry

log = logging.getLogger(__name__)


async def report() -> str:
    cfg = settings()
    lines = ["Stanje alata:"]
    for t in sorted(registry._TOOLS.values(), key=lambda t: t.name):
        reason = t.disabled_reason()
        lines.append(f"❌ {t.name} — {reason}" if reason else f"✅ {t.name}")
    lines += [
        f"Automatski poslovi: {'uključeni' if cfg.scheduler_enabled == 'on' else 'isključeni'}",
        f"Modeli: brzi {cfg.model_fast}, glavni {cfg.model_main}, duboki {cfg.model_deep}",
        f"Embeddinzi: {cfg.embed_provider}, {cfg.embed_model} ({cfg.embed_dim} dimenzija)",
    ]
    if cfg.embed_provider == "openai" and not cfg.openai_api_key:
        lines.append("⚠️ Embeddinzi: nedostaje OPENAI_API_KEY.")
    try:
        row = await pool().fetchrow("""SELECT
            (SELECT count(*) FROM documents) AS documents,
            (SELECT count(*) FROM chunks) AS chunks,
            (SELECT count(*) FROM facts) AS facts""")
        lines.append("Baza: dostupna")
        lines.append(
            f"Dokumenti: {row['documents']}, delovi: {row['chunks']}, činjenice: {row['facts']}"
        )
    except Exception:
        log.exception("Provera baze nije uspela")
        lines.append("Baza: nedostupna (detalji u logu).")
    return "\n".join(lines)

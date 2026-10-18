"""RAG alat: model sam odlučuje kad da pretraži bazu znanja (agentic RAG).

Klasičan RAG uvek ubaci rezultate pretrage u prompt. Ovde je pretraga alat:
model je zove samo kad pitanje traži lične dokumente, može da preformuliše
upit i da pretraži ponovo ako prvi rezultati nisu dobri.
"""

from datetime import date
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator

from dexter import sources
from dexter.config import settings
from dexter.rag import store
from dexter.rag.dates import period_bounds
from dexter.tools.registry import tool


class SearchArgs(BaseModel):
    upit: str = Field(
        description="Šta se traži. Može prirodnim jezikom ili tačnim pojmom (PIB, ime)."
    )
    izvor: str | None = Field(
        None, description="Opciono suzi na izvor: notion, drive, mail, razgovor, fajl, zakon."
    )
    limit: int = Field(6, ge=1, le=15)
    od: date | None = Field(None, description="Od datuma izvora, uključivo, YYYY-MM-DD u TIMEZONE.")
    do: date | None = Field(None, description="Do datuma izvora, uključivo, YYYY-MM-DD u TIMEZONE.")

    @model_validator(mode="after")
    def valid_period(self):
        period_bounds(self.od, self.do)
        return self


class ReindexArgs(BaseModel):
    izvor: str | None = Field(None, description="Izvor za osvežavanje; izostavi za sve podešene.")


@tool(
    "knowledge_reindex",
    "Osvežava indeks za semantičku pretragu. Bot ovo radi sam jednom "
    "dnevno — pozovi samo ako korisnik izričito traži ili ako pretraga ne nalazi nešto "
    "što je tek dodato.",
    enabled=lambda: bool(sources.available()),
)
async def knowledge_reindex(args: ReindexArgs) -> dict:
    return await sources.reindex(args.izvor)


@tool(
    "knowledge_search",
    "Pretražuje korisnikove dokumente, beleške, fajlove i dnevne sažetke razgovora "
    "po značenju i po tačnim rečima "
    "(hybrid). Vraća odlomke sa izvorom. Kad odgovaraš na osnovu njih, navedi izvor "
    "(naslov). Za traženi period prosledi od/do. Datum izvora je izmena Notion/Drive "
    "dokumenta, datum mejla/razgovora ili izmena lokalnog fajla; za Telegram fajl datum uvoza. "
    "Ako odlomci ne sadrže odgovor, reci to — ne dopunjuj iz glave.",
)
async def knowledge_search(args: SearchArgs) -> dict:
    hits = await store.search(
        args.upit, limit=args.limit, source=args.izvor, date_from=args.od, date_to=args.do
    )
    if not hits:
        return {"rezultati": [], "napomena": "Ništa nije nađeno. Probaj drugačiji upit."}
    return {
        "rezultati": [
            {
                "izvor": h.title,
                "url": h.url,
                "odlomak": h.text,
                "ocena": h.score,
                "datum": h.modified_at.astimezone(ZoneInfo(settings().timezone)).isoformat()
                if h.modified_at
                else None,
            }
            for h in hits
        ]
    }

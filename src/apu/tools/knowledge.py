"""RAG alat: model sam odlučuje kad da pretraži bazu znanja (agentic RAG).

Klasičan RAG uvek ubaci rezultate pretrage u prompt. Ovde je pretraga alat:
model je zove samo kad pitanje traži lične dokumente, može da preformuliše
upit i da pretraži ponovo ako prvi rezultati nisu dobri.
"""

from pydantic import BaseModel, Field

from apu import sources
from apu.rag import store
from apu.tools.registry import tool


class SearchArgs(BaseModel):
    upit: str = Field(
        description="Šta se traži. Može prirodnim jezikom ili tačnim pojmom (PIB, ime)."
    )
    izvor: str | None = Field(
        None, description="Opciono suzi na izvor: notion, drive, mail, razgovor, fajl, zakon."
    )
    limit: int = Field(6, ge=1, le=15)


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
    "(naslov). Ako odlomci ne sadrže odgovor, reci to — ne dopunjuj iz glave.",
)
async def knowledge_search(args: SearchArgs) -> dict:
    hits = await store.search(args.upit, limit=args.limit, source=args.izvor)
    if not hits:
        return {"rezultati": [], "napomena": "Ništa nije nađeno. Probaj drugačiji upit."}
    return {
        "rezultati": [
            {"izvor": h.title, "url": h.url, "odlomak": h.text, "ocena": h.score} for h in hits
        ]
    }

"""Alati za memoriju: model može eksplicitno da zapamti, pretraži i zaboravi."""

from pydantic import BaseModel, Field

from dexter import memory
from dexter.tools.registry import tool


class SaveArgs(BaseModel):
    tekst: str = Field(description="Činjenica u jednoj rečenici, npr. 'Marko je knjigovođa'.")
    kategorija: str = Field("ostalo", description=f"Jedna od: {', '.join(memory.CATEGORIES)}.")


class RecallArgs(BaseModel):
    upit: str = Field(description="Šta tražiš, prirodnim jezikom.")


class ForgetArgs(BaseModel):
    id: int = Field(description="ID činjenice iz memory_search ili memory_list.")


class ListArgs(BaseModel):
    kategorija: str | None = Field(None, description="Opciono: samo jedna kategorija.")


@tool(
    "memory_save",
    "Trajno pamti činjenicu o korisniku. Koristi kad korisnik kaže 'zapamti' ili otkrije "
    "nešto važno i trajno. Činjenice se i same izvlače posle razgovora, pa ovo nije "
    "potrebno za svaku sitnicu.",
)
async def memory_save(args: SaveArgs) -> dict:
    return await memory.save(args.tekst, args.kategorija)


@tool("memory_search", "Pretražuje dugoročnu memoriju po značenju.")
async def memory_search(args: RecallArgs) -> list[dict]:
    return await memory.recall(args.upit, limit=15)


@tool("memory_list", "Prikazuje sve zapamćene činjenice (ili jednu kategoriju).")
async def memory_list(args: ListArgs) -> list[dict]:
    return await memory.list_all(args.kategorija)


@tool(
    "memory_forget",
    "Briše činjenicu iz memorije. Koristi kad korisnik kaže da nešto nije tačno.",
    confirm=True,
)
async def memory_forget(args: ForgetArgs) -> dict:
    return {"obrisano": await memory.forget(args.id)}

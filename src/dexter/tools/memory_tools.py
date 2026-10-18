"""Alati za memoriju: model može eksplicitno da zapamti, pretraži i zaboravi."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class UpdateArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: int = Field(ge=1, strict=True)
    tekst: str | None = Field(None, min_length=1, max_length=10000)
    kategorija: Literal["osoba", "preferencija", "projekat", "navika", "cilj", "ostalo"] | None = (
        None
    )

    @field_validator("tekst")
    @classmethod
    def valid_text(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Prazna činjenica.")
        return value

    @model_validator(mode="after")
    def has_change(self):
        if self.tekst is None and self.kategorija is None:
            raise ValueError("Navedi novi tekst ili kategoriju činjenice.")
        return self


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
    "memory_update",
    "Menja postojeću zapamćenu činjenicu kad se nešto promeni. ID nađi preko memory_list "
    "ili iz uglastih zagrada u činjenicama iz konteksta. Prosledi novi tekst i/ili kategoriju; "
    "nenavedeno ostaje isto, ID ostaje isti. Tekst dobija novi vektor za pretragu. "
    "Ne dodaj novu činjenicu umesto izmene postojeće.",
    requires=[],
)
async def memory_update(args: UpdateArgs) -> dict:
    return await memory.update(args.id, args.tekst, args.kategorija)


@tool(
    "memory_forget",
    "Briše činjenicu iz memorije. Koristi kad korisnik kaže da nešto nije tačno.",
    confirm=True,
)
async def memory_forget(args: ForgetArgs) -> dict:
    return {"obrisano": await memory.forget(args.id)}

"""Alati navika: nazivi kolona dolaze iz konfiguracije, a ne iz pretpostavke modela."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from dexter.services import checklist, dnevnik, insights
from dexter.tools.registry import tool


class DayArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    datum: str | None = Field(
        None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="YYYY-MM-DD; podrazumevano danas po TIMEZONE.",
    )

    @field_validator("datum")
    @classmethod
    def valid_date(cls, value):
        return date.fromisoformat(value).isoformat() if value is not None else None


class MarkArgs(DayArgs):
    stavke: dict[str, StrictBool] = Field(
        min_length=1, description="Tačni nazivi iz checklist_get i true/false vrednosti."
    )


class DiaryArgs(DayArgs):
    raspolozenje: Literal["Odlično", "Dobro", "Neutralno", "Loše", "Teško"] | None = None
    energija: Literal["Visoka", "Srednja", "Niska"] | None = None
    kljucnaRec: str | None = Field(None, min_length=1, max_length=2000)


class InsightsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dana: int = Field(30, ge=1, le=366, description="Koliko dana unazad, uključujući danas.")


@tool(
    "checklist_get",
    "Čita dnevnu checklistu navika za dati datum (podrazumevano danas): tačne nazive stavki, "
    "označene stavke, šta fali, skor i nedeljni cilj iz CHECKLIST_CILJNA_STAVKA / "
    "CHECKLIST_CILJ_NEDELJNO (npr. broj treninga). Koristi za 'šta mi fali danas' ili "
    "'koliko sam puta bio u teretani'. Čitanje ne kreira red.",
    requires=checklist.REQUIRES,
)
async def checklist_get(args: DayArgs) -> dict:
    return await checklist.get(args.datum)


@tool(
    "checklist_mark",
    "Označava ili skida oznaku stavki; ako dnevni red ne postoji, kreira ga. Koristi TAČNE "
    "nazive iz checklist_get (CHECKLIST_POZITIVNE / CHECKLIST_IZBEGAVANJA); prvo ih pročitaj "
    'ako ih ne znaš. Menja samo prosleđene stavke. VAŽNO: stavke sa "Bez " su OBRNUTE: '
    'true znači uspešno IZBEGAO. "Jeo sam slatko" → {"Bez slatkog": false}; '
    '"nisam jeo slatko" → {"Bez slatkog": true}. Za obične stavke true znači urađeno.',
    requires=checklist.REQUIRES,
)
async def checklist_mark(args: MarkArgs) -> dict:
    return await checklist.mark(args.stavke, args.datum)


@tool(
    "checklist_create_day",
    "Kreira dnevni red checkliste (naslov = srpsko ime dana). Ako postoji, ne pravi duplikat. "
    "Koristi samo ako korisnik izričito traži. Za automatski upis u 05:00 potrebni su "
    "posebno podešen jutarnji posao i uključen raspored; ne pretpostavljaj da su uključeni.",
    requires=checklist.REQUIRES,
)
async def checklist_create_day(args: DayArgs) -> dict:
    return await checklist.create_day(args.datum)


@tool(
    "dnevnik_get",
    "Čita dnevnik za datum (podrazumevano danas): raspoloženje, energija, ključna reč i "
    "lista praznih polja. Čitanje ne kreira zapis.",
    requires=dnevnik.REQUIRES,
)
async def dnevnik_get(args: DayArgs) -> dict:
    return await dnevnik.get(args.datum)


@tool(
    "dnevnik_write",
    "Upisuje dnevnik; kreira zapis ako ga nema. Upiši SAMO polja koja je korisnik zaista "
    "pomenuo; izostavljena ostaju netaknuta. raspolozenje: Odlično, Dobro, Neutralno, Loše, "
    "Teško; energija: Visoka, Srednja, Niska; kljucnaRec: kratka reč/fraza za dan. "
    "VAŽNO: ako rezultat 'prazno' nije prazan, OBAVEZNO pitaj za ta polja. "
    "Ne izmišljaj raspoloženje, energiju ni ključnu reč.",
    requires=dnevnik.REQUIRES,
)
async def dnevnik_write(args: DiaryArgs) -> dict:
    return await dnevnik.write(**args.model_dump(exclude_none=True))


@tool(
    "insights_get",
    "Statistika checkliste i dnevnika za period (30 dana): prosečan skor, nizovi uspešnih "
    "kalendarskih dana, najčešće preskočene stavke, najbolji/najgori dan u nedelji i veze "
    "navika sa raspoloženjem/energijom. Koristi za 'kako mi ide', 'šta mi najviše smeta'. "
    "Sve su tvrde brojke, ne ML; prepričaj ih bez nepokrivenih zaključaka. Veza zahteva "
    "najmanje 3 dana sa i 3 bez označene navike uz poznatu ocenu; nije uzročnost. "
    "Ako postoji 'napomena', OBAVEZNO je pomeni.",
    requires=checklist.REQUIRES,
)
async def insights_get(args: InsightsArgs) -> dict:
    return await insights.get(args.dana)

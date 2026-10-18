"""Jedan zahtev za pregled izvora i opciono čuvanje izveštaja u Google Doc."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from dexter.services import calendar, google, reports
from dexter.tools.registry import tool


class ReportArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str | None = Field(None, min_length=1, max_length=200)
    instructions: str = Field("", max_length=4000)
    from_: str | None = Field(None, alias="from")
    to: str | None = None
    includeTasks: bool = True
    includeCalendar: bool = True
    includeSites: bool = False
    saveToDoc: bool = True

    @field_validator("from_", "to")
    @classmethod
    def valid_date(cls, value):
        if value is not None:
            calendar.parse_time(value)
        return value


@tool(
    "generate_report",
    "Sastavlja uredan izveštaj iz stvarnih podataka: trenutni Notion TASK BOARD statusi, "
    "događaji iz kalendara u opsegu, opciono trenutni status sajtova. Čuva kao Google Doc "
    "i vraća link; saveToDoc=false vraća samo tekst. Koristi za 'napravi izveštaj', "
    "'sumiraj ovu nedelju u dokument', 'izveštaj o urađenom'. Nedeljni opseg je poslednjih "
    "7 dana; from/to su ISO datumi ili vreme sa zonom. Done nema datum završetka, pa ne "
    "tvrdi da su svi ti zadaci završeni u periodu. Greške izvora obavezno navedi. "
    "Ne šalje izveštaj drugim osobama i ne zakazuje posao.",
    requires=google.REQUIRES,
    max_result_chars=40000,
)
async def generate_report(args: ReportArgs) -> dict:
    return await reports.generate(args)

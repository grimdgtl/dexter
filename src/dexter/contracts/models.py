"""Model predlaže podatak i dokaz; ishod provere određuje isključivo kod."""

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Citation(StrictModel):
    strana: int = Field(ge=1)
    pasus: int = Field(ge=1)
    citat: str = Field(min_length=5, max_length=4000)


class Fact(StrictModel):
    vrednost: str | None = Field(None, max_length=1500)
    dokaz: Citation | None = None


class Party(StrictModel):
    naziv: Fact = Field(default_factory=Fact)
    uloga: Fact = Field(default_factory=Fact)
    # Broj uvek izvodi kod iz označenog pasusa, nikad iz modelske vrednosti.
    pib_dokaz: Citation | None = None


class Dates(StrictModel):
    zakljucenje: Fact = Field(default_factory=Fact)
    pocetak: Fact = Field(default_factory=Fact)
    istek: Fact = Field(default_factory=Fact)
    otkazni_rok: Fact = Field(default_factory=Fact)


class Obligation(StrictModel):
    ko: Fact = Field(default_factory=Fact)
    sta: Fact = Field(default_factory=Fact)
    do_kada: Fact = Field(default_factory=Fact)
    iznos: Fact = Field(default_factory=Fact)


class Extraction(StrictModel):
    strane: list[Party] = Field(default_factory=list, max_length=8)
    datumi: Dates = Field(default_factory=Dates)
    obaveze: list[Obligation] = Field(default_factory=list, max_length=12)


class Proposal(StrictModel):
    id: str
    tekst: str
    rok: str | None
    podsetnik: str | None
    izvor: str


class Review(StrictModel):
    id: str
    owner: int
    sha256: str
    naziv: str
    stranice: list[list[str]]
    izdvojeno: Extraction
    predlozi: list[Proposal]

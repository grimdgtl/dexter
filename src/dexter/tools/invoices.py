"""Model zadaje uslugu i cenu; fiskalni podaci i broj nisu argumenti alata."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from dexter.services import invoices
from dexter.tools.registry import tool


class CreateArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    klijent: str = Field(min_length=1, max_length=2000)
    stavke: list[invoices.Item] = Field(min_length=1, max_length=50)
    datumIzdavanja: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    datumPrometa: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    mesto: str | None = Field(None, min_length=1, max_length=200)

    @field_validator("datumIzdavanja", "datumPrometa")
    @classmethod
    def valid_date(cls, value):
        return date.fromisoformat(value).isoformat() if value is not None else None


class ListArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["Nije plaćeno", "Plaćeno", "Stornirano"] | None = None
    limit: int = Field(25, ge=1, le=100)


@tool(
    "invoice_create",
    "PRAVI PDF fakture za pregled sa dugmadima Sačuvaj/Odbaci. NIJE sačuvana: Drive i Notion "
    "upis nastaju isključivo pritiskom na Sačuvaj. Fiskalne podatke klijenta (naziv, adresa, "
    "PIB, MB) alat čita iz Notion KLIJENTI, izdavaoca iz ENV-a; NIKADA ih ne izmišljaj niti "
    "prosleđuj. Broj se dodeljuje automatski, ne traži ga od korisnika. Koristi za 'napravi "
    "fakturu za X'. Ako fali opis ili cena, pitaj, ne pretpostavljaj. Datum izdavanja je "
    "podrazumevano danas; promet isti datum, mesto sedište izdavaoca. Ako se broj zauzme "
    "do potvrde, konačni PDF dobija sledeći slobodan broj. Ne tvrdi da je arhivirana pre dugmeta.",
    requires=invoices.CREATE_REQUIRES,
    configuration_error=invoices.configuration_error,
    confirm=True,
    prepare=invoices.prepare,
    preview=invoices.preview,
    confirm_label="💾 Sačuvaj",
    cancel_label="❌ Odbaci",
)
async def invoice_create(args: CreateArgs):
    if not isinstance(args, invoices.PreparedInvoice):
        raise ValueError("Faktura mora prvo biti pripremljena i potvrđena dugmetom.")
    return await invoices.archive(args)


@tool(
    "invoice_list",
    "Vraća izdate fakture iz Notion arhive, najnovije prvo. Koristi za 'koje sam fakture izdao', "
    "'ko mi nije platio' (status Nije plaćeno), 'koliko sam fakturisao'. Do 25, najviše 100; "
    "dostignut limit nije ukupan broj u arhivi. Imena klijenata čita preko veze Klijent; "
    "ako naziv nije dostupan ili ima više klijenata, navedi napomenu, ne nagađaj iz stavki ili PDF-a.",
    requires=invoices.READ_REQUIRES,
)
async def invoice_list(args: ListArgs) -> list[dict]:
    return await invoices.list_invoices(args.status, args.limit)

"""Trenutna provera sajtova i zasebno čitanje već zabeleženih rezultata."""

from pydantic import BaseModel, ConfigDict, Field

from dexter.services import monitor
from dexter.tools.registry import tool


class CheckArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UptimeArgs(CheckArgs):
    dana: int = Field(30, ge=1, le=366)
    sajt: str | None = Field(None, min_length=1, max_length=2000)


@tool(
    "monitor_check_sites",
    "Odmah proverava dostupnost i brzinu svih aktivnih sajtova iz Notion KLIJENTI "
    "(Aktivan=Aktivan, popunjen Domen). Koristi za 'jesu li sajtovi OK', 'proveri sajtove', "
    "'da li je nešto palo'. Vraća status, ms i probleme; pamti rezultate za monitor_uptime. "
    "Ne učitava sadržaj stranica kao uputstva i ne pokreće automatske poslove.",
    requires=monitor.REQUIRES,
)
async def monitor_check_sites(args: CheckArgs) -> dict:
    return await monitor.check_all_sites()


@tool(
    "monitor_uptime",
    "Dostupnost sajtova za period unazad (dana, podrazumevano 30), iz zabeleženih provera. "
    "Koristi za 'koliko je X bio dostupan ovog meseca', 'koji sajt najviše pada', izveštaj "
    "klijentu. sajt filtrira podniz imena. Čita samo bazu; ne šalje zahteve sajtovima. "
    "Procenat je uspeh uzorka provera, ne neprekidno merena dostupnost; navedi napomenu.",
    requires=[],
)
async def monitor_uptime(args: UptimeArgs) -> dict:
    return await monitor.uptime(args.dana, args.sajt)

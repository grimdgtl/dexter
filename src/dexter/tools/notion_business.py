"""Klijenti, poslovni zadaci i beleške; lična To-do lista ostaje poseban alat."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from dexter.services import notion_clients as clients
from dexter.services import notion_work as work
from dexter.tools.registry import tool

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Active = Literal["Aktivan", "Arhiva", "U izradi"]
Status = Literal["Not started", "In progress", "Done"]


class ClientFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    nazivZaFakturu: Text | None = Field(
        None, description="Pun pravni naziv koji je korisnik naveo."
    )
    domen: Text | None = Field(None, description="Sajt klijenta; prihvata i primer.rs bez sheme.")
    email: Text | None = None
    telefon: Text | None = None
    pib: Text | None = Field(
        None,
        description="Samo PIB koji je korisnik naveo ili koji je pročitan iz Notion-a; "
        "nikad ne izmišljaj.",
    )
    mb: Text | None = Field(
        None, description="Matični broj iz navedenih podataka, nikad iz pretpostavke."
    )
    adresa: Text | None = Field(
        None, description="Adresa iz navedenih podataka, nikad iz pretpostavke."
    )
    grad: Text | None = None
    opis: Text | None = None
    aktivan: Active | None = None
    tip: Literal["Klijent", "Interni", "Veliki ugovor"] | None = None
    status: Literal["Plaćeno", "Nije plaćeno", "Ne plaća"] | None = None
    faktura: Literal["Poslato", "Nije poslato", "Ne plaća"] | None = None
    ponuda: Literal["Poslato", "Nije poslato"] | None = None
    trajanje: Literal["Mesečno", "12 meseci", "6 meseci", "Nema održavanja"] | None = None
    odrzavanjeCena: float | None = Field(
        None,
        ge=0,
        allow_inf_nan=False,
        strict=True,
        description="Cena održavanja u RSD koju je korisnik naveo.",
    )
    elementor: Literal["Da", "Ne"] | None = None
    mojHosting: Literal["Da", "Ne"] | None = None

    @field_validator("*", mode="before")
    @classmethod
    def skip_blank(cls, value):
        return None if isinstance(value, str) and not value.strip() else value


class ClientAddArgs(ClientFields):
    naziv: Text


class ClientUpdateArgs(ClientFields):
    klijent: Text = Field(
        description="Naziv postojećeg klijenta; dovoljan nedvosmislen deo naziva."
    )
    naziv: Text | None = None


class ClientListArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    aktivan: Active | None = None
    limit: int = Field(50, ge=1, le=100)


class ClientFindArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: Text = Field(description="Deo naziva klijenta.")


class TaskAddArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Text
    status: Status = "Not started"


class TaskListArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Status | None = None
    limit: int = Field(25, ge=1, le=100)


class TaskStatusArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    taskId: UUID = Field(description="ID poslovnog zadatka iz notion_list_tasks.")
    status: Status


class KnowledgeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Text
    content: str = Field(
        "", max_length=100000, description="Tekst beleške; svaki neprazan novi red postaje pasus."
    )


@tool(
    "client_add",
    "Upisuje klijenta u Notion KLIJENTI. Alat SAM prepoznaje postojeću firmu i kada je naziv "
    "drugačije napisan ('Petar Pavlović PR ABC STUDIO' i 'ABC Studio'): "
    "tada dopunjuje POSTOJEĆI "
    "red, bez novog. Ako firme nema, kreira je. Koristi kada korisnik pošalje podatke firme; "
    "naziv prosledi kako ga je naveo. Upiši SAMO navedene podatke; ne izmišljaj PIB, MB, adresu "
    "ni cenu. Ne dodaj podrazumevane vrednosti opcionih polja. 'dopunjen' i 'poruka' govore "
    "šta se desilo — javi to korisniku. Ako ima više kandidata, traži precizniji naziv.",
    requires=clients.REQUIRES,
)
async def client_add(args: ClientAddArgs) -> dict:
    return await clients.add(args.model_dump(exclude_none=True))


@tool(
    "client_update",
    "Menja POSTOJEĆEG klijenta. Prosledi samo polja koja se menjaju; izostavljena ostaju "
    "netaknuta. Koristi za 'dopuni PIB za X', 'označi da je Y platio', 'prebaci Z u arhivu'. "
    "PIB, MB, adresu i cenu uzmi isključivo iz navedenih podataka ili pročitanog Notion-a; "
    "nikada ne izmišljaj. Više kandidata zahteva precizniji naziv, bez pogađanja.",
    requires=clients.REQUIRES,
)
async def client_update(args: ClientUpdateArgs) -> dict:
    return await clients.update(
        args.klijent, args.model_dump(exclude_none=True, exclude={"klijent"})
    )


@tool(
    "client_list",
    "Vraća klijente sa svim podacima, opciono po statusu saradnje. Koristi za 'koji su mi "
    "klijenti', 'ko mi nije platio', 'koliko imam aktivnih klijenata'. Podrazumevano do 50; "
    "ako je dostignut limit, ne predstavljaj listu kao ukupan broj u bazi.",
    requires=clients.REQUIRES,
    max_result_chars=100000,
)
async def client_list(args: ClientListArgs) -> list[dict]:
    return await clients.list_clients(args.aktivan, args.limit)


@tool(
    "client_find",
    "Traži klijenta po delu naziva i vraća podatke. Koristi kada treba PIB, adresa, email "
    "ili status konkretnog klijenta. Traži i naziv za fakturu; tačan naziv ima prednost.",
    requires=clients.REQUIRES,
    max_result_chars=100000,
)
async def client_find(args: ClientFindArgs) -> list[dict]:
    return await clients.find(args.query)


@tool(
    "notion_add_task",
    "Dodaje novi poslovni zadatak u Notion TASK BOARD. Koristi za 'dodaj mi ovo u taskove', "
    "'podseti me da uradim X', 'ubaci na listu'. Za LIČNE zadatke koristi todo_add. "
    "Status je podrazumevano Not started. Sam upis zadatka ne zakazuje podsetnik.",
    requires=work.TASK_REQUIRES,
)
async def notion_add_task(args: TaskAddArgs) -> dict:
    return await work.add_task(args.title, args.status)


@tool(
    "notion_list_tasks",
    "Vraća poslovne zadatke iz TASK BOARD-a za 'šta imam da radim', 'otvoreni taskovi' "
    "ili jutarnji pregled. Opciono filtriraj status; bez filtera vraća sve statuse, "
    "uključujući Done (do 25). Za ličnu listu koristi todo_list.",
    requires=work.TASK_REQUIRES,
)
async def notion_list_tasks(args: TaskListArgs) -> list[dict]:
    return await work.list_tasks(args.status, args.limit)


@tool(
    "notion_update_task_status",
    "Menja status postojećeg POSLOVNOG zadatka, npr. 'označi X kao gotovo'. Prvo pozovi "
    "notion_list_tasks da nađeš ID; za lične zadatke koristi todo_set_status.",
    requires=work.TASK_REQUIRES,
)
async def notion_update_task_status(args: TaskStatusArgs) -> dict:
    return await work.update_task(str(args.taskId), args.status)


@tool(
    "notion_add_knowledge",
    "Dodaje belešku u Notion Knowledge Base kao podstranicu. Koristi za 'dodaj ovo u "
    "knowledge base', 'zabeleži ovo', 'sačuvaj mi ovaj link/tekst'. Svaki neprazan red je "
    "pasus. Ako rezultat kaže 'delimicno', prenesi napomenu i link: ne tvrdi da je ceo tekst "
    "sačuvan i ne ponavljaj kreiranje. Ovaj upis nije osvežavanje indeksa knowledge_search.",
    requires=work.KB_REQUIRES,
)
async def notion_add_knowledge(args: KnowledgeArgs) -> dict:
    return await work.add_knowledge(args.title, args.content)

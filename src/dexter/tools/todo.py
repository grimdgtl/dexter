"""Alati lične To-do liste; poslovni TASK BOARD je zasebna baza."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from dexter.services import todo
from dexter.tools.registry import tool

Status = Literal["Not started", "In progress", "Done"]


class ListArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Status | None = None
    limit: int = Field(25, ge=1, le=100)


class AddArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    zadatak: str = Field(min_length=1, max_length=2000)
    oblast: Literal["Zdravlje", "Kuća", "Finansije", "Ljudi", "Učenje", "Ostalo"] | None = None
    prioritet: Literal["Visok", "Srednji", "Nizak"] | None = None
    rok: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="Rok YYYY-MM-DD.")

    @field_validator("rok")
    @classmethod
    def valid_date(cls, value):
        return date.fromisoformat(value).isoformat() if value is not None else None


class StatusArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    zadatakId: UUID = Field(description="ID ličnog zadatka iz todo_list.")
    status: Status


@tool(
    "todo_list",
    "Vraća lične zadatke sa To-do liste (Life stranica). Podrazumevano samo otvorene. "
    "Ovo je LIČNA lista (kućni poslovi, ljudi, zdravlje) — za poslovne zadatke koristi "
    "notion_list_tasks.",
    requires=todo.REQUIRES,
)
async def todo_list(args: ListArgs) -> list[dict]:
    return await todo.list_tasks(args.status, args.limit)


@tool(
    "todo_add",
    "Dodaje nov lični zadatak na To-do listu (Life stranica).",
    requires=todo.REQUIRES,
)
async def todo_add(args: AddArgs) -> dict:
    return await todo.add_task(**args.model_dump())


@tool(
    "todo_set_status",
    'Menja status ličnog zadatka — npr. kad korisnik kaže da je nešto završio postavi na "Done". '
    "Prvo pozovi todo_list da nađeš ID zadatka.",
    requires=todo.REQUIRES,
)
async def todo_set_status(args: StatusArgs) -> dict:
    return await todo.set_status(str(args.zadatakId), args.status)

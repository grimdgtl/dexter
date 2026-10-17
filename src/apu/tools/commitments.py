from typing import Literal

from pydantic import BaseModel, Field

from apu import commitments
from apu.tools.registry import tool


class ListArgs(BaseModel):
    status: Literal["open", "done", "all"] = "open"


class DoneArgs(BaseModel):
    id: int = Field(gt=0, description="ID stvarne obaveze iz commitments_list.")


@tool(
    "commitments_list", "Prikazuje obaveze koje je korisnik preuzeo u razgovoru, sa osobom i rokom."
)
async def commitments_list(args: ListArgs) -> list[dict]:
    return await commitments.list_all(args.status)


@tool(
    "commitment_done",
    "Označava obavezu kao završenu kad korisnik kaže da ju je uradio. ID nađi kroz commitments_list.",
)
async def commitment_done(args: DoneArgs) -> dict:
    return {"završeno": await commitments.done(args.id), "id": args.id}

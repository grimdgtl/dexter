"""Potvrda vezuje tačno pregledani predlog; neizvestan Notion upis se ne ponavlja."""

import re
from datetime import date
from uuid import UUID

from notion_client import APIResponseError
from pydantic import Field, PrivateAttr

from dexter import commitments
from dexter.config import settings
from dexter.contracts import service
from dexter.contracts.models import Proposal, Review, StrictModel
from dexter.db import pool
from dexter.proactive_time import local_now
from dexter.services import notion_work as work


def title(proposal: Proposal) -> str:
    text = re.sub(r" \([\d., ]+ [A-Z]{3}\)$", "", proposal.tekst)
    text = " ".join(text.split())
    return text if len(text) <= 100 else text[:99].rstrip() + "…"


def display_date(value: str | None) -> str:
    return date.fromisoformat(value).strftime("%d.%m.%Y.") if value else "bez roka"


def description(args: "TaskArgs") -> str:
    p = args._proposal
    return (
        f"Ugovor: {args._review.naziv}\nObaveza: {p.tekst}\n"
        f"Rok: {display_date(p.rok)}\n"
        f"Telegram podsetnik: {display_date(p.podsetnik) if p.podsetnik else 'nije predložen'}\n"
        f"Izvor:\n{p.izvor}"
    )


class TaskArgs(StrictModel):
    pregled_id: UUID
    predlog_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    _review: Review | None = PrivateAttr(None)
    _proposal: Proposal | None = PrivateAttr(None)
    _destination: dict | None = PrivateAttr(None)


async def prepare(args: TaskArgs) -> TaskArgs:
    args._review = await service.load(str(args.pregled_id))
    args._proposal = next((p for p in args._review.predlozi if p.id == args.predlog_id), None)
    if args._proposal is None:
        raise ValueError("Predlog ne pripada ovom pregledu ugovora.")
    if args._proposal.rok and date.fromisoformat(args._proposal.rok) < local_now().date():
        raise ValueError("Rok ovog predloga je prošao; ništa nije zakazano.")
    args._destination = await work.contract_destination()
    return args


def preview(args: TaskArgs) -> str:
    p = args._proposal
    if p is None or args._review is None or args._destination is None:
        raise ValueError("Predlog nije pripremljen.")
    return (
        f"Zadatak: {p.tekst}\n"
        f"Lista: {args._destination['putanja']}\n"
        f"Rok: {display_date(p.rok)}\n"
        f"Podsetnik: {display_date(p.podsetnik) if p.podsetnik else 'nije predložen'}\n"
        f"Ugovor: {args._review.naziv}\n"
        "Izvor i citat biće u opisu zadatka. Sačuvaj samo ako želiš ovaj zadatak."
    )


async def save(args: TaskArgs) -> dict:
    if not args._proposal or not args._review or not args._destination:
        raise ValueError("Zadatak nema pregledan predlog.")
    p, review = args._proposal, args._review
    if p.rok and date.fromisoformat(p.rok) < local_now().date():
        raise ValueError("Rok je prošao od pripreme. Zadatak nije upisan.")
    state_key = f"contract:task:{review.id}:{p.id}"
    # Metapodaci se proveravaju pre rezervacije: lokalno odbijanje nije neizvestan upis.
    if await work.contract_destination() != args._destination:
        raise ValueError("Odredište se promenilo. Ponovo pripremi zadatak za potvrdu.")
    claimed = await pool().fetchval(
        "INSERT INTO kv_state(key,value) VALUES($1,$2) ON CONFLICT DO NOTHING RETURNING key",
        state_key,
        {"status": "pokusano"},
    )
    state = await pool().fetchval("SELECT value FROM kv_state WHERE key=$1", state_key)
    if not claimed and not state.get("task"):
        raise ValueError(
            "Upis je već pokušavan, a ishod nije poznat. Proveri Notion; zahtev nije ponovljen."
        )
    if not claimed and not state.get("odrediste"):
        return {
            "status": "ranije_sacuvano_u_life",
            "notion": state["task"],
            "poruka": "Zadatak već postoji. Proveri postojeći zapis preko linka; "
            "novi zadatak i podsetnik nisu napravljeni.",
            "napomena": "Raniji upis je koristio Life. Proveri da je postojeći zapis u Work-u.",
        }
    if claimed:
        try:
            task = await work.add_contract_task(
                title(p),
                rok=p.rok,
                destination=args._destination,
                description=description(args),
            )
        except ValueError:
            await pool().execute("DELETE FROM kv_state WHERE key=$1", state_key)
            raise
        except APIResponseError as exc:
            if 400 <= exc.status < 500 and exc.status != 408:
                await pool().execute("DELETE FROM kv_state WHERE key=$1", state_key)
            raise
        state = {"status": "notion_upisano", "task": task, "odrediste": args._destination}
        await pool().execute(
            "UPDATE kv_state SET value=$2,updated_at=now() WHERE key=$1", state_key, state
        )
    if p.rok and not state.get("podsetnik_sacuvan"):
        shown = preview(args)
        item = commitments.Commitment(
            tekst=f"{p.tekst[:800]} [ugovor {review.id}]",
            rok=date.fromisoformat(p.rok),
            dokaz=shown[:1400],
        )
        # Korisnik je dugmetom odobrio upravo ovaj prikaz, uključujući dan podsetnika.
        await commitments.save(
            item, shown, remind_on=date.fromisoformat(p.podsetnik) if p.podsetnik else None
        )
        state["podsetnik_sacuvan"] = True
        await pool().execute(
            "UPDATE kv_state SET value=$2,updated_at=now() WHERE key=$1", state_key, state
        )
    return {
        "status": "vec_sacuvano" if not claimed else "sacuvano",
        "notion": state["task"],
        "odrediste": state["odrediste"],
        "podsetnik": p.podsetnik,
        "poruka": ("Zadatak već postoji u Work-u: " if not claimed else "Sačuvano u Work-u: ")
        + title(p)
        + f"\nRok: {display_date(p.rok)}"
        + (f"\nPodsetnik: {display_date(p.podsetnik)}" if p.podsetnik else ""),
        "napomena": "Automatsko slanje podsetnika je isključeno."
        if settings().scheduler_enabled == "off"
        else "",
    }

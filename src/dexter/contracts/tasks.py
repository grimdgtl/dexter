"""Potvrda vezuje tačno pregledani predlog; neizvestan Notion upis se ne ponavlja."""

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
        f"Ugovor: {args._review.naziv}\nZadatak: {p.tekst}\n"
        f"Notion odredište: {args._destination['putanja']} (Work)\n"
        f"Baza: {args._destination['baza_id']}\n"
        f"Notion rok: {p.rok or 'bez roka'}\n"
        f"Telegram podsetnik: {p.podsetnik or 'nije predložen'} (jutarnja provera obaveza)\n"
        f"Izvor: {p.izvor}\nProveri da želiš ovaj zadatak na svojoj listi, pa potvrdi."
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
            "napomena": "Ovaj predlog je ranije upisan u Life. Nije napravljen Work duplikat "
            "niti novi podsetnik. Proveri link i premesti postojeći red u Work ako je još "
            "u Life; postojeći podsetnik je nepromenjen.",
        }
    if claimed:
        try:
            task = await work.add_contract_task(
                f"{p.tekst}\n[Ugovor: {review.naziv}; {p.izvor[:400]}]"[:1900],
                rok=p.rok,
                destination=args._destination,
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
        "napomena": "Automatsko slanje podsetnika je isključeno."
        if settings().scheduler_enabled == "off"
        else "Podsetnik proverava postojeći posao obaveza.",
    }

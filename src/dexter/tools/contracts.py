"""Model može samo da učita pregled ili pripremi već postojeći predlog za potvrdu."""

from uuid import UUID

from dexter.contracts import service, tasks
from dexter.contracts.models import StrictModel
from dexter.services import notion_work
from dexter.tools.registry import tool


class ReviewArgs(StrictModel):
    pregled_id: UUID


@tool(
    "contract_get",
    "Čita postojeći pregled ugovora po ID-ju. Za novi ugovor korisnik šalje PDF/sliku uz /ugovor. Status citat proveren nije potvrda pravnog tumačenja. Nepotvrđene vrednosti ne predstavljaj kao činjenice.",
    max_result_chars=50000,
)
async def contract_get(args: ReviewArgs) -> str:
    return service.render(await service.load(str(args.pregled_id)))


@tool(
    "contract_task_create",
    "Priprema postojeći predlog iz pregleda ugovora za poslovnu Work bazu. Korisnik "
    "potvrđuje odredište, zadatak i prikazani Telegram podsetnik dugmetom. Ne prima "
    "tekst, rokove ni fiskalne podatke od modela.",
    confirm=True,
    prepare=tasks.prepare,
    preview=tasks.preview,
    requires=notion_work.TASK_REQUIRES,
)
async def contract_task_create(args: tasks.TaskArgs) -> dict:
    return await tasks.save(args)

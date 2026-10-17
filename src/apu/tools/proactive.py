from pydantic import BaseModel, Field

from apu import proactive
from apu.tools.registry import tool


class LogArgs(BaseModel):
    dana: int = Field(7, ge=1, le=31)


@tool(
    "proactive_log",
    "Pregled odluka za proaktivne poruke: razlog slanja ili ćutanja, ishod i greške. Ne izvršava akcije.",
)
async def proactive_log(args: LogArgs) -> list[dict]:
    return await proactive.history(args.dana)

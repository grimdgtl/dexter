"""Registar alata: jedna definicija → šema za model, validacija, izvršavanje.

U staroj verziji je svaki alat bio opisan na dva mesta: šema u
definitions.js (950 linija) i funkcija u tools/index.js. Lako se raziđu.
Ovde je alat jedna Python funkcija sa dekoratorom; JSON šemu za model
pravi pydantic iz tipa argumenata, pa šema i kod ne mogu da se raziđu.

    class Args(BaseModel):
        grad: str = Field(description="Ime grada")

    @tool("weather_get", "Vremenska prognoza.")
    async def weather_get(args: Args) -> dict: ...

Šta registar radi za svaki alat:
  - gasi alat ako mu fali konfiguracija (`enabled`), pa ga model ni ne vidi
  - validira ulaz modela pre izvršavanja (pogrešan tip → jasna greška modelu)
  - hvata izuzetke, pa jedan pokvaren alat ne obara ceo odgovor
  - skraćuje predugačak rezultat da ne pojede kontekst
  - alate sa `confirm=True` NE izvršava odmah, nego ih stavlja na čekanje
    dok korisnik ne pritisne dugme (mejl, faktura, brisanje...)
"""

import json
import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from apu.config import settings

log = logging.getLogger(__name__)

MAX_RESULT_CHARS = 12_000
CONFIRM_TTL_S = 30 * 60


@dataclass
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    fn: Callable[[Any], Awaitable[Any]]
    enabled: Callable[[], bool] = lambda: True
    confirm: bool = False
    # Kako da se akcija prikaže korisniku pre potvrde (samo za confirm=True)
    preview: Callable[[Any], str] | None = None
    requires: tuple[str, ...] = ()
    prepare: Callable[[Any], Awaitable[Any]] | None = None

    def disabled_reason(self) -> str | None:
        cfg = settings()
        missing = [name for name in self.requires if not getattr(cfg, name.lower(), None)]
        if missing:
            return "Nedostaje: " + ", ".join(missing)
        if not self.enabled():
            return "Isključeno podešavanjima."
        return None

    def is_enabled(self) -> bool:
        return self.disabled_reason() is None

    def schema(self) -> dict:
        s = self.args_model.model_json_schema()
        s.pop("title", None)
        return {"name": self.name, "description": self.description, "input_schema": s}


@dataclass
class Pending:
    tool: Tool
    args: BaseModel
    created: float = field(default_factory=time.monotonic)


_TOOLS: dict[str, Tool] = {}
_PENDING: dict[str, Pending] = {}


def tool(
    name: str,
    description: str,
    *,
    enabled: Callable[[], bool] = lambda: True,
    confirm: bool = False,
    preview: Callable[[Any], str] | None = None,
    requires: list[str] | None = None,
    prepare: Callable[[Any], Awaitable[Any]] | None = None,
):
    """Dekorator koji registruje alat. Tip prvog argumenta je pydantic model ulaza."""

    def wrap(fn):
        args_model = next(iter(fn.__annotations__.values()))
        if name in _TOOLS:
            raise ValueError(f"Alat {name} je već registrovan.")
        _TOOLS[name] = Tool(
            name,
            description,
            args_model,
            fn,
            enabled,
            confirm,
            preview,
            tuple(requires or ()),
            prepare,
        )
        return fn

    return wrap


def enabled_tools() -> list[Tool]:
    return [t for t in _TOOLS.values() if t.is_enabled()]


def schemas() -> list[dict]:
    """Šeme za model, sortirane po imenu — stabilan redosled je bitan za prompt caching."""
    out = [t.schema() for t in sorted(enabled_tools(), key=lambda t: t.name)]
    if out:
        # Breakpoint na poslednjem alatu kešira SVE definicije alata.
        out[-1]["cache_control"] = {"type": "ephemeral"}
    return out


def _serialize(result: Any) -> str:
    text = (
        result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
    )
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + f"\n…(skraćeno, ukupno {len(text)} znakova)"
    return text


@dataclass
class Outcome:
    text: str  # ide modelu kao tool_result
    is_error: bool = False
    pending: tuple[str, str] | None = None  # (potvrda_id, opis) ako čeka dugme


async def execute(name: str, raw_input: dict) -> Outcome:
    t = _TOOLS.get(name)
    if t is None or not t.is_enabled():
        return Outcome(f"Alat {name} ne postoji ili nije uključen.", True)

    try:
        args = t.args_model.model_validate(raw_input)
    except ValidationError as e:
        return Outcome(f"Neispravni argumenti za {name}: {e.errors(include_url=False)}", True)

    if t.confirm:
        try:
            if t.prepare:
                args = await t.prepare(args)
            opis = t.preview(args) if t.preview else f"{name}({args.model_dump_json()})"
        except Exception as e:
            log.exception("Priprema alata %s nije uspela", name)
            return Outcome(f"Priprema nije uspela: {e}", True)
        token = secrets.token_urlsafe(8)
        _PENDING[token] = Pending(t, args)
        text = _serialize(
            {
                "status": "ceka_potvrdu",
                "opis": opis,
                "napomena": "Akcija NIJE izvršena. Korisnik dobija dugmad za potvrdu.",
            }
        )
        return Outcome(text, pending=(token, opis))

    try:
        return Outcome(_serialize(await t.fn(args)))
    except Exception as e:
        log.exception("Alat %s pukao", name)
        return Outcome(f"Greška u alatu {name}: {e}", True)


def pending_preview(token: str) -> str | None:
    p = _PENDING.get(token)
    return p.tool.preview(p.args) if p and p.tool.preview else None


async def confirm(token: str) -> str:
    """Poziva se kad korisnik pritisne 'Potvrdi'. Jedino mesto gde se akcija stvarno izvrši."""
    p = _PENDING.pop(token, None)
    if p is None or time.monotonic() - p.created > CONFIRM_TTL_S:
        return "Ova akcija je istekla ili je već obrađena."
    try:
        return _serialize(await p.tool.fn(p.args))
    except Exception as e:
        log.exception("Potvrđena akcija %s pukla", p.tool.name)
        return f"Greška: {e}"


def cancel(token: str) -> None:
    _PENDING.pop(token, None)

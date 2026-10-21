"""Registar alata: jedna definicija → šema za model, validacija, izvršavanje.

Alat je Python funkcija sa dekoratorom i Pydantic modelom ulaza. JSON šema
za LLM izvodi se iz tog modela, umesto odvojenog održavanja definicije i validacije.

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

from dexter.actions import ConfirmedAction, Document, PreparedAction
from dexter.config import settings

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
    requires_any: tuple[tuple[str, ...], ...] = ()
    confirm_label: str = "✅ Potvrdi"
    max_result_chars: int = MAX_RESULT_CHARS
    cancel_label: str = "❌ Otkaži"
    configuration_error: Callable[[], str | None] | None = None

    def disabled_reason(self) -> str | None:
        cfg = settings()
        missing = [name for name in self.requires if not getattr(cfg, name.lower(), None)]
        if missing:
            return "Nedostaje: " + ", ".join(missing)
        if self.requires_any and not any(
            all(getattr(cfg, name.lower(), None) for name in group) for group in self.requires_any
        ):
            return "Potrebno jedno od: " + " ili ".join(
                " + ".join(group) for group in self.requires_any
            )
        if self.configuration_error and (error := self.configuration_error()):
            return error
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
    document: Document | None = None


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
    requires_any: list[list[str]] | None = None,
    confirm_label: str = "✅ Potvrdi",
    max_result_chars: int = MAX_RESULT_CHARS,
    cancel_label: str = "❌ Otkaži",
    configuration_error: Callable[[], str | None] | None = None,
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
            tuple(tuple(group) for group in (requires_any or [])),
            confirm_label,
            max_result_chars,
            cancel_label,
            configuration_error,
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


def _serialize(result: Any, limit: int = MAX_RESULT_CHARS) -> str:
    text = (
        result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
    )
    if len(text) > limit:
        text = text[:limit] + f"\n…(skraćeno, ukupno {len(text)} znakova)"
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
        # PDF predlozi mogu biti veliki; novi zahtev uklanja istekle priloge iz memorije.
        for token, pending in list(_PENDING.items()):
            if time.monotonic() - pending.created > CONFIRM_TTL_S:
                _PENDING.pop(token, None)
        document = None
        try:
            if t.prepare:
                args = await t.prepare(args)
            if isinstance(args, PreparedAction):
                document, args = args.document, args.args
            opis = t.preview(args) if t.preview else f"{name}({args.model_dump_json()})"
        except Exception as e:
            log.exception("Priprema alata %s nije uspela", name)
            return Outcome(f"Priprema nije uspela: {e}", True)
        token = secrets.token_urlsafe(8)
        _PENDING[token] = Pending(t, args, document=document)
        text = _serialize(
            {
                "status": "ceka_potvrdu",
                "opis": opis,
                "napomena": "Akcija NIJE izvršena. Korisnik dobija dugmad za potvrdu.",
            }
        )
        return Outcome(text, pending=(token, opis))

    try:
        return Outcome(_serialize(await t.fn(args), t.max_result_chars))
    except Exception as e:
        log.exception("Alat %s pukao", name)
        return Outcome(f"Greška u alatu {name}: {e}", True)


def pending_preview(token: str) -> str | None:
    p = _PENDING.get(token)
    return p.tool.preview(p.args) if p and p.tool.preview else None


def pending_confirm_label(token: str) -> str:
    pending = _PENDING.get(token)
    return pending.tool.confirm_label if pending else "✅ Potvrdi"


def pending_cancel_label(token: str) -> str:
    pending = _PENDING.get(token)
    return pending.tool.cancel_label if pending else "❌ Otkaži"


def pending_document(token: str) -> Document | None:
    pending = _PENDING.get(token)
    return pending.document if pending else None


async def confirm(token: str) -> str | ConfirmedAction:
    """Poziva se kad korisnik pritisne 'Potvrdi'. Jedino mesto gde se akcija stvarno izvrši."""
    p = _PENDING.pop(token, None)
    if p is None or time.monotonic() - p.created > CONFIRM_TTL_S:
        return "Ova akcija je istekla ili je već obrađena."
    try:
        result = await p.tool.fn(p.args)
        if isinstance(result, ConfirmedAction):
            return ConfirmedAction(_serialize(result.result), result.document, result.successful)
        return _serialize(result)
    except Exception as e:
        log.exception("Potvrđena akcija %s pukla", p.tool.name)
        return f"Greška: {e}"


def cancel(token: str) -> None:
    _PENDING.pop(token, None)

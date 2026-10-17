"""Agentska petlja: model → alati → model … → odgovor.

Razlike u odnosu na claude.js:
  - prompt caching na tri mesta: alati, system prompt, istorija
  - nezavisni alati se izvršavaju paralelno (asyncio.gather)
  - memorija se ubacuje po relevantnosti, ne cela
  - model se bira po težini zahteva
  - svaki poziv se meri (tokeni, cena, latencija)
"""

import asyncio
import copy
import logging
from dataclasses import dataclass, field

from apu import llm, memory, usage
from apu.agent import history, summary
from apu.agent.prompts import SYSTEM_PROMPT, turn_context
from apu.agent.router import select_model
from apu.config import settings
from apu.tools import registry

log = logging.getLogger(__name__)

MAX_STEPS = 10
# Reference na pozadinske zadatke — inače ih garbage collector može ugasiti u letu.
_background: set[asyncio.Task] = set()


@dataclass
class AgentResult:
    text: str
    model: str
    # Akcije koje čekaju potvrdu korisnika: [(potvrda_id, opis)]
    pending: list[tuple[str, str]] = field(default_factory=list)


def _with_cache_breakpoint(messages: list[dict]) -> list[dict]:
    """Kopija poruka sa cache_control na poslednjem bloku → kešira se cela istorija."""
    msgs = copy.deepcopy(messages)
    last = msgs[-1]
    if isinstance(last["content"], str):
        last["content"] = [{"type": "text", "text": last["content"]}]
    last["content"][-1]["cache_control"] = {"type": "ephemeral"}
    return msgs


def _dump(blocks) -> list[dict]:
    """SDK objekti → čist dict za čuvanje u bazi i ponovno slanje."""
    return [b.model_dump(exclude_none=True) for b in blocks]


async def _run_tools(calls) -> tuple[list[dict], list[tuple[str, str]]]:
    outcomes = await asyncio.gather(*(registry.execute(c.name, c.input) for c in calls))
    results = [
        {"type": "tool_result", "tool_use_id": c.id, "content": o.text, "is_error": o.is_error}
        for c, o in zip(calls, outcomes, strict=True)
    ]
    return results, [o.pending for o in outcomes if o.pending]


async def run(chat_id: int, user_content: str | list[dict], *, on_text=None) -> AgentResult:
    """Obrađuje jednu korisnikovu poruku (tekst ili lista blokova sa slikom)."""
    with usage.turn(chat_id):
        return await _run(chat_id, user_content, on_text=on_text)


async def _run(chat_id: int, user_content: str | list[dict], *, on_text=None) -> AgentResult:
    cfg = settings()

    if isinstance(user_content, str):
        model, user_text = await select_model(user_content)
        blocks: list[dict] = [{"type": "text", "text": user_text}]
    else:
        blocks = user_content
        user_text = " ".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        model = cfg.model_main

    facts = await memory.recall(user_text) if user_text.strip() else []
    notes = await history.load_notes(chat_id)
    past, previous_summary = await summary.load_context(chat_id, cfg.history_turns)
    runtime_context = turn_context(
        facts, notes=[n["text"] for n in notes], summary=previous_summary
    )
    blocks = [
        {
            "type": "text",
            "text": turn_context(facts, notes=[n["text"] for n in notes]),
        },
        *blocks,
    ]
    new_messages: list[dict] = [{"role": "user", "content": blocks}]

    tools = registry.schemas()
    system = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
    pending: list[tuple[str, str]] = []
    final_text = ""
    used_model = model

    for step in range(MAX_STEPS):
        if on_text is not None:
            await on_text("")
        complete = llm.create if on_text is None else llm.stream
        streaming_args = {} if on_text is None else {"on_text": on_text}
        messages = _with_cache_breakpoint(past + new_messages)
        # Sažetak ide samo u tekući zahtev; kopije u istorijskim porukama bi uvećale kontekst.
        messages[len(past)]["content"][0]["text"] = runtime_context
        response = await complete(
            purpose="chat",
            model=model,
            max_tokens=cfg.max_tokens,
            system=system,
            tools=tools,
            messages=messages,
            **streaming_args,
        )
        text = llm.text_of(response)
        used_model = getattr(response, "model", model)

        if response.stop_reason == "max_tokens":
            # Presečeno usred alata → ne upisuj nesparene pozive (vidi history.py).
            log.warning("max_tokens u koraku %d — odbacujem nesparene pozive.", step)
            final_text = text or "Zahtev je preobiman za jedan odgovor — podeli ga na manje delove."
            new_messages.append({"role": "assistant", "content": final_text})
            break

        new_messages.append({"role": "assistant", "content": _dump(response.content)})

        if response.stop_reason != "tool_use":
            final_text = text or "(prazan odgovor)"
            break

        calls = [b for b in response.content if b.type == "tool_use"]
        log.info("Korak %d: %s", step, ", ".join(c.name for c in calls))
        results, step_pending = await _run_tools(calls)
        pending += step_pending
        new_messages.append({"role": "user", "content": results})
    else:
        final_text = "Zahtev traži previše koraka — pokušaj da ga podeliš."
        new_messages.append({"role": "assistant", "content": final_text})

    await history.append(chat_id, new_messages, note_ids=[n["id"] for n in notes])

    # Memorija se izvlači u pozadini — korisnik ne čeka na to.
    task = asyncio.create_task(memory.extract_and_save(user_text, final_text))
    _background.add(task)
    task.add_done_callback(_background.discard)

    return AgentResult(text=final_text, model=used_model, pending=pending)

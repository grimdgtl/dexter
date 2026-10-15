"""Testovi za čistu logiku — rade bez baze, mreže i API ključeva."""

from datetime import datetime

import pytest
from pydantic import BaseModel

from apu.agent.history import sanitize, trim_turns
from apu.agent.prompts import SYSTEM_PROMPT, turn_context
from apu.agent.router import pick_model
from apu.config import settings
from apu.memory import parse_facts
from apu.pismo import u_latinicu
from apu.rag.chunking import chunk_text
from apu.rag.store import rrf
from apu.tools import registry
from evals.rag_eval import metrics

# ── Pismo ───────────────────────────────────────────────────


def test_latinica():
    assert u_latinicu("Љубав и њега") == "Ljubav i njega"
    assert u_latinicu("ЊЕГОВ ЏЕП") == "NJEGOV DŽEP"
    assert u_latinicu("Hello 123 😀") == "Hello 123 😀"


# ── Chunking ────────────────────────────────────────────────


def test_chunks_cover_whole_document():
    text = "\n\n".join(f"Pasus {i}. " + "reč " * 80 for i in range(30))
    chunks = chunk_text(text, title="Dok")
    assert len(chunks) > 1
    assert all(c.startswith("Dok\n") for c in chunks)
    assert all(len(c) <= 1200 + 250 for c in chunks)  # veličina + naslov + preklapanje
    assert "Pasus 29" in chunks[-1]  # stara verzija bi ovo izgubila (2000 znakova)


def test_long_sentence_is_split():
    chunks = chunk_text("reč " * 2000)
    assert len(chunks) > 3


def test_empty():
    assert chunk_text("   ") == []


# ── Hybrid / RRF ────────────────────────────────────────────


def test_rrf_rewards_agreement():
    scores = rrf([1, 2, 3], [3, 4])
    # 3 je u obe liste, pa pobeđuje 1 koji je prvi samo u jednoj
    assert max(scores, key=scores.get) == 3


# ── Istorija ────────────────────────────────────────────────


def _tool_use(i):
    return {
        "role": "assistant",
        "content": [{"type": "tool_use", "id": i, "name": "x", "input": {}}],
    }


def _tool_result(i):
    return {"role": "user", "content": [{"type": "tool_result", "tool_use_id": i, "content": "ok"}]}


def test_trim_never_starts_with_tool_result():
    msgs = [
        {"role": "user", "content": "prva"},
        _tool_use("a"),
        _tool_result("a"),
        {"role": "assistant", "content": "odg"},
        {"role": "user", "content": "druga"},
        {"role": "assistant", "content": "odg2"},
    ]
    out = trim_turns(msgs, 1)
    assert out[0]["content"] == "druga"


def test_sanitize_drops_unpaired_tool_use():
    msgs = [
        {"role": "user", "content": "zdravo"},
        {"role": "assistant", "content": [{"type": "text", "text": "evo"},
                                          {"type": "tool_use", "id": "z", "name": "x", "input": {}}]},
        {"role": "user", "content": "nova poruka"},
    ]  # fmt: skip
    out = sanitize(msgs)
    assert out[1]["content"] == [{"type": "text", "text": "evo"}]
    assert sanitize([{"role": "user", "content": "a"}, _tool_use("b"), _tool_result("b")]) == [
        {"role": "user", "content": "a"}, _tool_use("b"), _tool_result("b")
    ]  # fmt: skip


def test_sanitize_drops_orphan_tool_result():
    out = sanitize([{"role": "user", "content": "a"}, _tool_result("x")])
    assert out == [{"role": "user", "content": "a"}]


# ── Registar alata ──────────────────────────────────────────


class _Args(BaseModel):
    broj: int


@registry.tool("test_dupli", "Duplira broj.")
async def _dupli(args: _Args) -> dict:
    return {"rezultat": args.broj * 2}


@registry.tool("test_slanje", "Šalje nešto.", confirm=True, preview=lambda a: f"Pošalji {a.broj}")
async def _slanje(args: _Args) -> str:
    return f"poslato {args.broj}"


async def test_tool_runs_and_validates():
    ok = await registry.execute("test_dupli", {"broj": 21})
    assert ok.text == '{"rezultat": 42}' and not ok.is_error
    bad = await registry.execute("test_dupli", {"broj": "nije broj"})
    assert bad.is_error


async def test_confirm_tool_does_not_run_until_confirmed():
    out = await registry.execute("test_slanje", {"broj": 7})
    assert out.pending is not None and "NIJE izvršena" in out.text
    token, opis = out.pending
    assert opis == "Pošalji 7"
    assert await registry.confirm(token) == "poslato 7"
    assert "istekla" in await registry.confirm(token)  # drugi put ne može


def test_schemas_sorted_and_cached():
    s = registry.schemas()
    names = [x["name"] for x in s]
    assert names == sorted(names)
    assert s[-1]["cache_control"] == {"type": "ephemeral"}
    assert all("cache_control" not in x for x in s[:-1])


# ── Prompt / router / memorija ──────────────────────────────


def test_system_prompt_is_static():
    # Ako se ovo promeni u funkciju koja ubacuje vreme, keš prestaje da radi.
    assert isinstance(SYSTEM_PROMPT, str) and "{" not in SYSTEM_PROMPT


def test_turn_context_has_time_and_facts():
    from zoneinfo import ZoneInfo

    now = datetime(2026, 10, 13, 9, 5, tzinfo=ZoneInfo("Europe/Belgrade"))
    ctx = turn_context([{"id": 3, "text": "Marko je knjigovođa"}], now)
    assert "utorak, 2026-10-13 09:05" in ctx and "[3] Marko je knjigovođa" in ctx


@pytest.mark.parametrize(
    ("text", "tier"),
    [
        ("kakvo je vreme", "main"),
        ("/duboko razradi plan za Pigeon", "deep"),
        ("analiziraj ugovor i uporedi ga sa prošlim", "deep"),
    ],
)
def test_router(text, tier):
    model, _ = pick_model(text)
    assert model == getattr(settings(), f"model_{tier}")


def test_parse_facts_tolerates_fences():
    raw = '```json\n[{"tekst": "Marko je knjigovođa", "kategorija": "osoba"}, {"x": 1}]\n```'
    assert parse_facts(raw) == [{"tekst": "Marko je knjigovođa", "kategorija": "osoba"}]
    assert parse_facts("nije json") == []


# ── Eval metrike ────────────────────────────────────────────


def test_eval_metrics():
    m = metrics([["a", "a", "b"], ["c", "d"]], ["b", "x"], k=2)
    assert m["recall_at_k"] == 0.5 and m["mrr"] == 0.25

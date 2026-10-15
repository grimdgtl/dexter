"""Integracioni testovi: prava baza (Postgres + pgvector), lažni model i embeddinzi.

Pokreću se samo kad postoji TEST_DATABASE_URL (prazna test baza!), npr:
    docker compose up -d db
    TEST_DATABASE_URL=postgresql://apu:apu@localhost:5432/apu_test pytest
"""

import asyncio
import hashlib
import math
import os
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL nije postavljen")


def fake_vector(text: str, dim: int = 1536) -> list[float]:
    """Deterministički 'embedding': vreća reči heširana u vektor. Dovoljno za testove."""
    v = [0.0] * dim
    for w in re.findall(r"\w+", text.lower()):
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % dim] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


@pytest.fixture
async def db(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    from apu import config
    from apu import db as dbmod

    config.settings.cache_clear()
    dbmod._pool = None

    async def fake_embed(texts, kind="passage"):
        return [fake_vector(t) for t in texts]

    async def fake_embed_one(text, kind="query"):
        return fake_vector(text)

    import apu.memory
    import apu.rag.store

    monkeypatch.setattr(apu.rag.store, "embed", fake_embed)
    monkeypatch.setattr(apu.rag.store, "embed_one", fake_embed_one)
    monkeypatch.setattr(apu.memory, "embed_one", fake_embed_one)

    pool = await dbmod.connect()
    await pool.execute(
        "TRUNCATE messages, facts, documents, chunks, usage RESTART IDENTITY CASCADE"
    )
    yield pool
    await pool.close()
    dbmod._pool = None


async def test_rag_index_and_hybrid_search(db):
    from apu.rag import store

    long_doc = "\n\n".join(f"Pasus {i} o održavanju sajtova i hostingu." for i in range(80))
    n = await store.upsert_document("notion:odrz", "notion", "Održavanje", long_doc)
    assert n > 1
    await store.upsert_document(
        "notion:abc", "notion", "ABC Studio", "Klijent ABC Studio, PIB 108073515, Beograd."
    )
    # Nepromenjen dokument se ne indeksira ponovo (ne troši embedding pozive).
    assert await store.upsert_document("notion:abc", "notion", "ABC Studio",
                                       "Klijent ABC Studio, PIB 108073515, Beograd.") == 0  # fmt: skip

    hits = await store.search("108073515")
    assert hits[0].document_id == "notion:abc"
    assert hits[0].keyword_rank == 1  # tačan broj nalazi full-text deo

    # Deo sa kraja dugog dokumenta je pretraživ (stara verzija je videla samo 2000 znakova).
    hits = await store.search("Pasus 79")
    assert any("Pasus 79" in h.text for h in hits)


async def test_memory_dedupes(db):
    from apu import memory

    first = await memory.save("Marko je knjigovođa firme", "osoba")
    again = await memory.save("Marko je knjigovođa firme.", "osoba")
    assert again["azurirano"] and again["id"] == first["id"]
    assert len(await memory.list_all()) == 1
    recalled = await memory.recall("ko je Marko knjigovođa")
    assert recalled and recalled[0]["text"].startswith("Marko")


async def test_agent_loop_parallel_tools_caching_and_history(db, monkeypatch):
    import apu.tools  # noqa: F401  registruje alate
    from apu import llm, memory
    from apu.agent import history, loop
    from apu.agent.prompts import SYSTEM_PROMPT

    await memory.save("Korisnik voli kratke odgovore", "preferencija")

    calls: list[dict] = []

    def block(**kw):
        return SimpleNamespace(**kw, model_dump=lambda exclude_none=True, kw=kw: dict(kw))

    def resp(content, stop):
        u = SimpleNamespace(input_tokens=100, output_tokens=20,
                            cache_read_input_tokens=50, cache_creation_input_tokens=0)  # fmt: skip
        return SimpleNamespace(content=content, stop_reason=stop, usage=u)

    async def fake_create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:  # model traži dva alata odjednom
            return resp(
                [block(type="tool_use", id="t1", name="memory_list", input={}),
                 block(type="tool_use", id="t2", name="memory_search", input={"upit": "odgovori"})],
                "tool_use",
            )  # fmt: skip
        return resp([block(type="text", text="Evo, kratko: sve je u redu.")], "end_turn")

    monkeypatch.setattr(llm.client().messages, "create", fake_create)
    monkeypatch.setattr(memory, "extract_and_save", lambda *a: _noop())

    result = await loop.run(42, "da li korisnik voli kratke odgovore?")
    assert result.text == "Evo, kratko: sve je u redu."

    # Prompt caching: system statičan sa breakpointom, alati sa breakpointom na kraju,
    # i poslednja poruka sa breakpointom (kešira istoriju).
    for c in calls:
        assert c["system"][0]["text"] == SYSTEM_PROMPT
        assert c["system"][0]["cache_control"] == {"type": "ephemeral"}
        assert c["tools"][-1]["cache_control"] == {"type": "ephemeral"}
        assert c["messages"][-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    # Drugi poziv nosi oba tool_result-a u JEDNOJ poruci (paralelno izvršavanje).
    results = calls[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]
    # Kontekst sa vremenom i relevantnom činjenicom ide uz poruku, ne u system.
    first_user = calls[0]["messages"][-1]["content"][0]["text"]
    assert "<kontekst>" in first_user and "kratke odgovore" in first_user

    saved = await history.load(42, 12)
    assert [m["role"] for m in saved] == ["user", "assistant", "user", "assistant"]
    assert all("cache_control" not in str(m) for m in saved)  # breakpoint se ne čuva

    n = await db.fetchval("SELECT count(*) FROM usage WHERE purpose = 'chat'")
    assert n == 2


async def _noop():
    return 0


async def test_parallel_messages_in_same_chat_preserve_history(db, monkeypatch):
    from apu import llm, memory, telegram_bot
    from apu.agent import history, loop

    monkeypatch.setattr(telegram_bot, "_chat_locks", {})
    monkeypatch.setattr(memory, "extract_and_save", AsyncMock())
    run = AsyncMock(wraps=loop.run)
    monkeypatch.setattr(loop, "run", run)
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    requests = []

    async def fake_create(**kwargs):
        requests.append(kwargs["messages"])
        text = kwargs["messages"][-1]["content"][-1]["text"]
        if text == "Prva":
            first_started.set()
            await release_first.wait()
        answer = {"type": "text", "text": f"Odgovor: {text}"}
        block = SimpleNamespace(**answer, model_dump=lambda **kwargs: answer.copy())
        return SimpleNamespace(content=[block], stop_reason="end_turn")

    monkeypatch.setattr(llm, "create", fake_create)
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=42))
    ctx = SimpleNamespace(
        bot=SimpleNamespace(send_message=AsyncMock(), send_chat_action=AsyncMock())
    )
    async with asyncio.timeout(5):
        async with asyncio.TaskGroup() as group:
            group.create_task(telegram_bot._answer(update, ctx, "Prva"))
            await first_started.wait()
            group.create_task(telegram_bot._answer(update, ctx, "Druga"))
            # Daj drugoj poruci priliku da uđe dok prvi model još čeka.
            await asyncio.sleep(0)
            try:
                assert run.await_count == 1
                assert len(requests) == 1
            finally:
                release_first.set()

    assert len(requests) == 2
    assert [m["role"] for m in requests[1]] == ["user", "assistant", "user"]
    assert requests[1][1]["content"][0]["text"] == "Odgovor: Prva"
    saved = await history.load(42, 12)
    assert [m["role"] for m in saved] == ["user", "assistant", "user", "assistant"]
    assert [m["content"][-1]["text"] for m in saved] == [
        "Prva",
        "Odgovor: Prva",
        "Druga",
        "Odgovor: Druga",
    ]
    if loop._background:
        await asyncio.gather(*loop._background)

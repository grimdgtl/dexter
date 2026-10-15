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

import asyncpg
import pytest
from pydantic import BaseModel

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
        "TRUNCATE messages, pending_notes, facts, documents, chunks, usage RESTART IDENTITY CASCADE"
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


@pytest.fixture
async def note_model(monkeypatch):
    from apu import llm, memory
    from apu.agent import loop

    answer = {"type": "text", "text": "U redu."}
    block = SimpleNamespace(**answer, model_dump=lambda **kwargs: answer.copy())
    create = AsyncMock(return_value=SimpleNamespace(content=[block], stop_reason="end_turn"))
    monkeypatch.setattr(llm, "create", create)
    monkeypatch.setattr(memory, "extract_and_save", AsyncMock())
    yield create
    if loop._background:
        await asyncio.gather(*loop._background)


@pytest.mark.parametrize("action", ["ok", "no"])
async def test_button_note_joins_next_user_context(db, monkeypatch, note_model, action):
    from apu import telegram_bot
    from apu.agent import history, loop
    from apu.agent.prompts import SYSTEM_PROMPT
    from apu.tools import registry

    class Args(BaseModel):
        pass

    fn = AsyncMock(return_value="Сачувано.")
    tool = registry.Tool("test_potvrda", "Test potvrde.", Args, fn, confirm=True)
    monkeypatch.setattr(registry, "_PENDING", {"token": registry.Pending(tool, Args())})
    query = SimpleNamespace(
        data=f"{action}:token",
        message=SimpleNamespace(text="Predlog akcije"),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=1), callback_query=query)
    await history.append(
        1,
        [
            {"role": "user", "content": "Pripremi akciju."},
            {"role": "assistant", "content": "Čeka potvrdu."},
        ],
    )
    await history.add_note(99, "Drugi razgovor.")
    await telegram_bot.on_button(update, SimpleNamespace())

    notes = await history.load_notes(1)
    assert len(notes) == 1
    note = notes[0]["text"]
    if action == "ok":
        fn.assert_awaited_once()
        assert "potvrdio akciju" in note and "Sačuvano." in note
    else:
        fn.assert_not_awaited()
        assert "otkazao" in note
    assert "token" not in registry._PENDING
    assert await db.fetchval("SELECT count(*) FROM messages WHERE chat_id = 1") == 2

    # I slike moraju da dobiju napomenu unutar iste korisničke poruke.
    content = (
        "Šta je urađeno?"
        if action == "ok"
        else [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": ""}},
            {"type": "text", "text": "Pogledaj sliku."},
        ]
    )
    await loop.run(1, content)
    request = note_model.await_args.kwargs
    assert request["system"][0]["text"] == SYSTEM_PROMPT
    context = request["messages"][-1]["content"][0]["text"]
    assert note in context and context.endswith("</kontekst>")
    assert [m["role"] for m in await history.load(1, 12)] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert await history.load_notes(1) == []
    assert len(await history.load_notes(99)) == 1

    await loop.run(1, "Nastavimo.")
    assert note not in note_model.await_args.kwargs["messages"][-1]["content"][0]["text"]


@pytest.mark.parametrize("error", [RuntimeError, asyncio.CancelledError])
async def test_note_survives_failed_model_call(db, note_model, error):
    from apu.agent import history, loop

    await history.add_note(1, "Potvrđena akcija.")
    notes = await history.load_notes(1)
    note_model.side_effect = error("Prekinut odgovor")
    with pytest.raises(error):
        await loop.run(1, "Šta je urađeno?")
    assert await history.load_notes(1) == notes
    assert await history.load(1, 12) == []


async def test_note_added_during_answer_waits_for_next_turn(db, note_model):
    from apu.agent import history, loop

    await history.add_note(1, "Prva napomena.")
    await history.add_note(1, "Druga napomena.")

    async def create(**kwargs):
        await history.add_note(1, "Kasnija napomena.")
        return note_model.return_value

    note_model.side_effect = create
    await loop.run(1, "Nastavi.")
    context = note_model.await_args.kwargs["messages"][-1]["content"][0]["text"]
    assert context.index("Prva napomena.") < context.index("Druga napomena.")
    assert "Kasnija napomena." not in context
    assert [n["text"] for n in await history.load_notes(1)] == ["Kasnija napomena."]


async def test_failed_history_write_keeps_notes(db):
    from apu.agent import history

    await history.add_note(1, "Potvrđena akcija.")
    notes = await history.load_notes(1)
    with pytest.raises(asyncpg.CheckViolationError):
        await history.append(
            1,
            [
                {"role": "user", "content": "Nastavi."},
                {"role": "neispravna", "content": "Greška pri upisu"},
            ],
            note_ids=[n["id"] for n in notes],
        )
    assert await history.load_notes(1) == notes
    assert await history.load(1, 12) == []


async def test_reset_clears_only_current_chat_notes(db):
    from apu.agent import history

    for chat_id in (1, 2):
        await history.add_note(chat_id, "Napomena.")
        await history.append(chat_id, [{"role": "user", "content": "Poruka."}])
    await history.clear(1)
    assert await history.load_notes(1) == []
    assert await history.load(1, 12) == []
    assert len(await history.load_notes(2)) == 1
    assert len(await history.load(2, 12)) == 1

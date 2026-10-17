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
from uuid import uuid4

import asyncpg
import httpx
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
        "TRUNCATE conversation_context, kv_state, job_runs, messages, pending_notes, facts, documents, chunks, usage RESTART IDENTITY CASCADE"
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

    monkeypatch.setattr(telegram_bot.settings(), "streaming", "off")

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


@pytest.fixture
async def migration_conn(db):
    name = "migration_" + uuid4().hex
    await db.execute(f'CREATE DATABASE "{name}"')
    conn = await asyncpg.connect(DB_URL, database=name)
    try:
        yield conn
    finally:
        await conn.close()
        await db.execute(f'DROP DATABASE "{name}"')


@pytest.mark.parametrize("legacy", [False, True])
async def test_migrations_are_idempotent_and_preserve_existing_data(migration_conn, legacy):
    from apu import db as dbmod

    conn = migration_conn
    if legacy:
        for path in sorted(dbmod.MIGRATIONS_DIR.glob("*.sql"))[:2]:
            await conn.execute(path.read_text().replace("{{EMBED_DIM}}", "1536"))
        await conn.execute(
            "INSERT INTO messages (chat_id, role, content) VALUES (1, 'user', '\"Poruka\"')"
        )
        await conn.execute(
            "INSERT INTO documents (id, source, title, content_hash) VALUES ('legacy:1','fajl','Stari','staro')"
        )
    assert await dbmod.migrate(conn, 1536) == [
        p.name.split("_", 1)[0] for p in sorted(dbmod.MIGRATIONS_DIR.glob("*.sql"))
    ]
    rows = await conn.fetch("SELECT * FROM schema_migrations ORDER BY version")
    assert await dbmod.migrate(conn, 1536) == []
    assert await conn.fetch("SELECT * FROM schema_migrations ORDER BY version") == rows
    assert await conn.fetchval("SELECT count(*) FROM messages") == int(legacy)
    assert await conn.fetchval("SELECT to_regclass('kv_state')")
    assert await conn.fetchval("SELECT to_regclass('pending_notes')")
    if legacy:
        row = await conn.fetchrow(
            "SELECT modified_at, content_text FROM documents WHERE id='legacy:1'"
        )
        assert row["modified_at"] is row["content_text"] is None


async def test_migration_failure_rolls_back_schema_and_version(migration_conn, tmp_path):
    from apu import db as dbmod

    (tmp_path / "001_test.sql").write_text("CREATE TABLE migration_probe (id int);")
    (tmp_path / "002_bad.sql").write_text("SELECT missing_migration_function();")
    with pytest.raises(asyncpg.UndefinedFunctionError):
        await dbmod.migrate(migration_conn, 1536, tmp_path)
    assert await migration_conn.fetchval("SELECT to_regclass('migration_probe')") is None
    assert await migration_conn.fetchval("SELECT to_regclass('schema_migrations')") is None


async def test_status_reports_database_counts(db):
    from apu import status

    text = await status.report()
    assert "Baza: dostupna" in text
    assert "Dokumenti: 0, delovi: 0, činjenice: 0" in text


@pytest.mark.parametrize("success", [True, False])
async def test_jobs_retry_record_and_notify_once(db, monkeypatch, success):
    from apu import jobs

    sleep = AsyncMock()
    monkeypatch.setattr(jobs.asyncio, "sleep", sleep)
    bot = SimpleNamespace(send_message=AsyncMock())
    fn = AsyncMock(
        side_effect=[
            RuntimeError("Prva"),
            RuntimeError("Druga"),
            42 if success else RuntimeError("Коначна грешка"),
        ]
    )
    result = await jobs.run_job("Test", fn, bot=bot)
    assert result == (42 if success else None)
    assert [c.args[0] for c in sleep.await_args_list] == [30, 60]
    row = await db.fetchrow("SELECT * FROM job_runs")
    assert row["ok"] == success and row["pokusaja"] == 3
    assert row["kraj"] >= row["start"]
    if success:
        bot.send_message.assert_not_awaited()
        assert row["greska"] is None
    else:
        bot.send_message.assert_awaited_once()
        assert "Konačna greška" in bot.send_message.await_args.args[1]
        assert row["greska"] == "Konačna greška"
    assert "Test: " in await jobs.report()


async def test_job_success_is_not_retried_if_recording_fails(db, monkeypatch):
    from apu import jobs

    # Drugi poziv execute upisuje ishod, pošto je fn već uspeo.
    real_execute = db.execute
    calls = 0

    async def execute(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("Prekid baze")
        return await real_execute(*args)

    fake_pool = SimpleNamespace(fetchval=db.fetchval, execute=execute)
    monkeypatch.setattr(jobs, "pool", lambda: fake_pool)
    fn = AsyncMock(return_value=1)
    with pytest.raises(RuntimeError, match="Prekid baze"):
        await jobs.run_job("Test", fn, bot=SimpleNamespace(send_message=AsyncMock()))
    fn.assert_awaited_once()


async def test_notion_source_full_pagination_skip_and_safe_removal(db, monkeypatch, respx_mock):
    from apu import config
    from apu.rag import store
    from apu.sources import notion

    monkeypatch.setenv("NOTION_API_KEY", "test-notion")
    config.settings.cache_clear()
    pages = [
        {
            "id": str(uuid4()),
            "object": "page",
            "properties": {},
            "url": "https://notion.so/test",
            "last_edited_time": "2026-09-15T12:00:00Z",
        }
        for _ in range(26)
    ]
    fail = False

    def search(request):
        import json

        cursor = json.loads(request.content).get("start_cursor")
        return httpx.Response(
            200,
            json={
                "results": pages[25:] if cursor else pages[:25],
                "has_more": not bool(cursor),
                "next_cursor": None if cursor else "jos",
            },
        )

    respx_mock.post("https://api.notion.com/v1/search").mock(side_effect=search)

    def blocks(request):
        if fail:
            return httpx.Response(
                403, json={"code": "restricted_resource", "message": "Zabranjeno"}
            )
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [
                                {
                                    "plain_text": "Sadržaj stranice o projektu i dogovorenim poslovima."
                                }
                            ]
                        },
                    }
                ],
                "has_more": False,
            },
        )

    respx_mock.get(url__regex=r"https://api\.notion\.com/v1/blocks/.*/children").mock(
        side_effect=blocks
    )
    await store.upsert_document("notion:stari", "notion", "Stari", "Stari dokument")
    await store.upsert_document("drive:drugi", "drive", "Drive", "Drugi izvor")
    assert (await notion.reindex())["ukupno"] == 26
    assert (
        str(await db.fetchval("SELECT modified_at FROM documents WHERE source='notion' LIMIT 1"))
        == "2026-09-15 12:00:00+00:00"
    )
    assert await db.fetchval("SELECT count(*) FROM documents WHERE id = 'notion:stari'") == 0
    embed = AsyncMock(wraps=store.embed)
    monkeypatch.setattr(store, "embed", embed)
    pages[0]["last_edited_time"] = "2026-10-01T12:00:00Z"
    result = await notion.reindex()
    assert result["preskoceno"] == 26 and result["indeksirano"] == 0
    embed.assert_not_awaited()
    assert (
        str(
            await db.fetchval(
                "SELECT modified_at FROM documents WHERE id=$1", f"notion:{pages[0]['id']}"
            )
        )
        == "2026-10-01 12:00:00+00:00"
    )
    await store.upsert_document("notion:zadrzi", "notion", "Zadrži", "Privremeno nedostupan")
    fail = True
    with pytest.raises(Exception, match="Zabranjeno"):
        await notion.reindex()
    assert await db.fetchval("SELECT count(*) FROM documents WHERE id = 'notion:zadrzi'") == 1
    assert await db.fetchval("SELECT count(*) FROM documents WHERE source = 'drive'") == 1
    config.settings.cache_clear()


async def test_drive_source_preserves_full_text_and_handles_missing_files(
    db, monkeypatch, respx_mock
):
    from apu import config
    from apu.rag import store
    from apu.services import google
    from apu.sources import drive

    for name in google.REQUIRES:
        monkeypatch.setenv(name, "test")
    config.settings.cache_clear()
    respx_mock.post("https://oauth2.googleapis.com/token").respond(
        200, json={"access_token": "access-test", "expires_in": 3600, "token_type": "Bearer"}
    )
    base = "https://www.googleapis.com/drive/v3/files"
    files = [
        {"id": "1", "name": "Doc", "mimeType": google.DOC, "modifiedTime": "2026-09-16T12:00:00Z"},
        {
            "id": "2",
            "name": "Tekst.md",
            "mimeType": "text/markdown",
            "modifiedTime": "2026-09-17T12:00:00Z",
        },
    ]

    def listing(request):
        return httpx.Response(
            200,
            json={
                "files": files[1:] if request.url.params.get("pageToken") else files[:1],
                **({} if request.url.params.get("pageToken") else {"nextPageToken": "drugi"}),
            },
        )

    route = respx_mock.get(base).mock(side_effect=listing)
    respx_mock.get(f"{base}/1/export").respond(
        200, text="Važan dokument o razvoju. " * 400 + "KRAJ-DOKUMENTA"
    )
    respx_mock.get(f"{base}/2", params__contains={"alt": "media"}).respond(
        200, text="Drugi dokument."
    )
    await store.upsert_document("drive:stari", "drive", "Stari", "Stari dokument")
    await store.upsert_document("notion:drugi", "notion", "Notion", "Drugi izvor")
    result = await drive.reindex()
    assert result["ukupno"] == 2 and result["obrisano"] == 1
    assert (
        str(await db.fetchval("SELECT modified_at FROM documents WHERE id='drive:1'"))
        == "2026-09-16 12:00:00+00:00"
    )
    assert await db.fetchval("SELECT count(*) FROM chunks WHERE text LIKE '%KRAJ-DOKUMENTA%'") == 1
    embed = AsyncMock(wraps=store.embed)
    monkeypatch.setattr(store, "embed", embed)
    assert (await drive.reindex())["preskoceno"] == 2
    embed.assert_not_awaited()
    route.respond(200, json={"files": [], "incompleteSearch": True})
    with pytest.raises(RuntimeError, match="nije potpuna"):
        await drive.reindex()
    assert await db.fetchval("SELECT count(*) FROM documents WHERE source = 'drive'") == 2
    route.respond(200, json={"files": []})
    assert (await drive.reindex())["obrisano"] == 2
    assert await db.fetchval("SELECT count(*) FROM documents WHERE source = 'notion'") == 1
    config.settings.cache_clear()


async def test_folder_import_pdf_text_markdown_and_unchanged_files(db, tmp_path, pdf_bytes):
    from scripts.ingest_folder import ingest_folder

    (tmp_path / "podfolder").mkdir()
    (tmp_path / "zakon.txt").write_text("Закон о раду и услови за престанак радног односа. " * 3)
    (tmp_path / "podfolder" / "zakon.txt").write_text(
        "Drugi zakon sa drugim pravilima i dodatnim obrazloženjem. " * 3
    )
    (tmp_path / "beleška.md").write_text(
        "# Napomena\n" + "Objašnjenje zakona i primene propisa. " * 3
    )
    (tmp_path / "propis.pdf").write_bytes(pdf_bytes)
    (tmp_path / "slika.png").write_bytes(b"nije za indeksiranje")
    os.utime(tmp_path / "zakon.txt", (1_789_473_600, 1_789_473_600))
    results = await ingest_folder(tmp_path, "zakon")
    assert len(results) == 4 and all(r["ok"] and r["delova"] for r in results)
    assert (
        await db.fetchval(
            "SELECT extract(epoch FROM modified_at) FROM documents WHERE id='zakon:zakon.txt'"
        )
        == 1_789_473_600
    )
    ids = {r["id"] for r in await db.fetch("SELECT id FROM documents WHERE source = 'zakon'")}
    assert {"zakon:zakon.txt", "zakon:podfolder/zakon.txt", "zakon:propis.pdf"} <= ids
    assert "Zakon o radu" in await db.fetchval(
        "SELECT text FROM chunks WHERE document_id = 'zakon:zakon.txt'"
    )
    assert all(r["delova"] == 0 for r in await ingest_folder(tmp_path, "zakon"))
    (tmp_path / "los.pdf").write_bytes(b"pokvaren PDF")
    results = await ingest_folder(tmp_path, "zakon")
    assert len(results) == 5 and sum(not r["ok"] for r in results) == 1


async def test_mail_source_evaluation_deduplication_and_safe_cleanup(
    db, imap_server, make_mail, monkeypatch
):
    import json
    import time

    from apu.rag import store
    from apu.sources import mail
    from evals.rag_eval import metrics

    shared = make_mail(
        subject="Ponuda Orion",
        text="Orion plan projekta i ugovor za razvoj sajta.",
        message_id="<orion@example.com>",
    )
    imap_server.messages["INBOX"] = [
        shared,
        make_mail(
            subject="Atlas", text="Dogovor o isporuci za Atlas.", message_id="<atlas@example.com>"
        ),
        make_mail(message_id="<stari@example.com>", when="Wed, 15 Oct 2024 10:00:00 +0200"),
    ]
    imap_server.messages["Poslato"] = [
        shared,
        make_mail(
            subject="Poslata ponuda",
            text="Poslata specifikacija implementacije.",
            message_id="<poslato@example.com>",
        ),
    ]
    expected = ["mail:<orion@example.com>"]
    start = time.perf_counter()
    before = metrics(
        [[h.document_id for h in await store.search("Orion", source="mail")]], expected, 5
    )
    before["ms_po_upitu"] = round(1000 * (time.perf_counter() - start), 2)
    result = await mail.reindex()
    assert result["indeksirano"] == result["ukupno"] == 3
    assert (
        str(
            await db.fetchval(
                "SELECT modified_at FROM documents WHERE id='mail:<orion@example.com>'"
            )
        )
        == "2026-10-15 08:00:00+00:00"
    )
    assert (
        await db.fetchval("SELECT count(*) FROM documents WHERE id = 'mail:<stari@example.com>'")
        == 0
    )
    start = time.perf_counter()
    after = metrics(
        [[h.document_id for h in await store.search("Orion", source="mail")]], expected, 5
    )
    after["ms_po_upitu"] = round(1000 * (time.perf_counter() - start), 2)
    assert before["recall_at_k"] == before["mrr"] == 0
    assert after["recall_at_k"] == after["mrr"] == 1
    print("F2.1 test eval:", json.dumps({"pre": before, "posle": after, "dokumenata": 3}))

    embed = AsyncMock(wraps=store.embed)
    monkeypatch.setattr(store, "embed", embed)
    assert (await mail.reindex())["preskoceno"] == 3
    embed.assert_not_awaited()
    await store.upsert_document("notion:drugi", "notion", "Drugi izvor", "Ne diraj Notion.")
    imap_server.messages["Poslato"] = []
    imap_server.fail_folder = "Poslato"
    with pytest.raises(RuntimeError, match="IMAP prekid"):
        await mail.reindex()
    assert await db.fetchval("SELECT count(*) FROM documents WHERE source = 'mail'") == 3
    assert imap_server.closed
    imap_server.fail_folder = None
    assert (await mail.reindex())["obrisano"] == 1
    assert await db.fetchval("SELECT count(*) FROM documents WHERE source = 'notion'") == 1


@pytest.fixture
def conversation_model(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from apu import config, llm
    from apu.sources import conversations

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 17, 3, 30, tzinfo=ZoneInfo("Europe/Belgrade")).astimezone(tz)

    async def create(**kwargs):
        prompt = kwargs["messages"][0]["content"]
        name = "Orion" if "Orion" in prompt else "Atlas"
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=f"Теме: {name}. Договор са Марком о року.")],
            stop_reason="end_turn",
            usage=SimpleNamespace(
                input_tokens=100,
                output_tokens=25,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )

    config.settings().telegram_owner_chat_id = 1
    config.settings().timezone = "Europe/Belgrade"
    model = AsyncMock(side_effect=create)
    monkeypatch.setattr(
        llm, "client", lambda: SimpleNamespace(messages=SimpleNamespace(create=model))
    )
    monkeypatch.setattr(conversations, "datetime", FrozenDateTime)
    return model


async def add_conversation_message(db, stamp, text, chat_id=1, role="user"):
    from datetime import datetime

    await db.execute(
        "INSERT INTO messages (chat_id, role, content, created_at) VALUES ($1, $2, $3, $4)",
        chat_id,
        role,
        text,
        datetime.fromisoformat(stamp),
    )


async def test_conversation_source_evaluation_dates_retry_and_reset(
    db, conversation_model, monkeypatch
):
    import json
    import time

    from apu import sources
    from apu.agent import history
    from apu.rag import store
    from apu.sources import conversations
    from evals.rag_eval import metrics

    await add_conversation_message(db, "2026-09-30T20:30:00+00:00", "Orion: dogovor sa Markom.")
    # Posle 22:00 UTC u ovoj zoni počinje sledeći lokalni dan.
    await add_conversation_message(db, "2026-09-30T22:30:00+00:00", "Atlas: rok je petak.")
    await add_conversation_message(db, "2026-10-16T22:30:00+00:00", "Današnja tema")
    await add_conversation_message(db, "2026-09-29T10:00:00+00:00", "DRUGI_KORISNIK", chat_id=2)
    expected = ["razgovor:2026-09-30", "razgovor:2026-10-01"]

    async def measure():
        start = time.perf_counter()
        result = metrics(
            [
                [h.document_id for h in await store.search(query, source="razgovor")]
                for query in ("Orion", "Atlas")
            ],
            expected,
            5,
        )
        result["ms_po_upitu"] = round(1000 * (time.perf_counter() - start) / 2, 2)
        return result

    before = await measure()
    assert (await sources.reindex("razgovor"))["razgovor"]["indeksirano"] == 2
    after = await measure()
    assert before["recall_at_k"] == before["mrr"] == 0
    assert after["recall_at_k"] == after["mrr"] == 1
    print("F2.2 test eval:", json.dumps({"pre": before, "posle": after, "dokumenata": 2}))
    assert conversation_model.await_count == 2
    assert (
        str(await db.fetchval("SELECT modified_at FROM documents WHERE id='razgovor:2026-09-30'"))
        == "2026-09-29 22:00:00+00:00"
    )
    assert await db.fetchval("SELECT count(*) FROM usage WHERE purpose='conversation_summary'") == 2
    assert not any("DRUGI_KORISNIK" in str(c) for c in conversation_model.call_args_list)
    assert "Dogovor sa Markom" in (await store.search("Orion", source="razgovor"))[0].text
    assert await db.fetchval("SELECT count(*) FROM documents WHERE source='razgovor'") == 2

    embed = AsyncMock(wraps=store.embed)
    monkeypatch.setattr(store, "embed", embed)
    assert (await conversations.reindex())["preskoceno"] == 2
    assert conversation_model.await_count == 2
    embed.assert_not_awaited()
    # Kasnije dodata stara poruka obnavlja samo odgovarajući dan.
    await add_conversation_message(db, "2026-09-30T21:00:00+00:00", "Orion: dodat dogovor.")
    assert (await conversations.reindex())["indeksirano"] == 1
    assert conversation_model.await_count == 3
    await history.clear(1)
    assert (await conversations.reindex())["ukupno"] == 0
    assert await db.fetchval("SELECT count(*) FROM documents WHERE source='razgovor'") == 2


@pytest.mark.parametrize("failure", ["model", "empty", "truncated", "embedding"])
async def test_conversation_failure_keeps_index_and_progress(
    db, conversation_model, monkeypatch, failure
):
    from apu.rag import store
    from apu.sources import conversations

    await add_conversation_message(db, "2026-09-30T10:00:00+00:00", "Orion dogovor.")
    await conversations.reindex()
    original_hash = await db.fetchval("SELECT content_hash FROM documents WHERE source='razgovor'")
    original_state = await db.fetchval("SELECT value FROM kv_state")
    await add_conversation_message(db, "2026-09-30T11:00:00+00:00", "Novi Orion rok.")
    original_create, original_embed = conversation_model.side_effect, store.embed
    if failure == "model":
        conversation_model.side_effect = RuntimeError("Prekid modela")
    elif failure in ("empty", "truncated"):

        async def invalid(**kwargs):
            result = await original_create(**kwargs)
            if failure == "empty":
                result.content = []
            else:
                result.stop_reason = "max_tokens"
            return result

        conversation_model.side_effect = invalid
    else:
        # Promenjen sažetak mora da pokuša nove embeddinge.
        async def changed(**kwargs):
            result = await original_create(**kwargs)
            result.content[0].text += " Novi rok."
            return result

        conversation_model.side_effect = changed
        monkeypatch.setattr(
            store, "embed", AsyncMock(side_effect=RuntimeError("Prekid embeddinga"))
        )
    with pytest.raises(RuntimeError):
        await conversations.reindex()
    assert (
        await db.fetchval("SELECT content_hash FROM documents WHERE source='razgovor'")
        == original_hash
    )
    assert await db.fetchval("SELECT value FROM kv_state") == original_state
    conversation_model.side_effect = original_create
    monkeypatch.setattr(store, "embed", original_embed)
    assert (await conversations.reindex())["indeksirano"] == 1
    assert (await conversations.reindex())["preskoceno"] == 1


async def test_chunk_sizes_evaluation_and_reindex_from_saved_text(db, monkeypatch):
    import json
    import time

    from apu.config import settings
    from apu.rag import store
    from evals.rag_eval import metrics
    from scripts.reindex_all import reindex_all

    cfg = settings()
    docs = []
    for i, name in enumerate(("Orion", "Atlas", "Vega", "Sirius", "Deneb", "Altair")):
        text = (
            "\n\n".join(
                f"Projekat {name}: oblast {j}. Dogovor o razvoju sajta, održavanju i rokovima. " * 4
                for j in range(12)
            )
            + f"\n\n{name}: konačni rok isporuke je petak, vodi ga Marko."
        )
        docs.append((f"test:{i}", name, text))
        await store.upsert_document(f"test:{i}", "test", name, text)
    results = []
    for size in (600, 1200, 2000):
        monkeypatch.setattr(cfg, "chunk_chars", size)
        await reindex_all()
        ranks = []
        start = time.perf_counter()
        for _, name, _ in docs:
            ranks.append(
                [h.document_id for h in await store.search(f"{name} konačni rok isporuke")]
            )
        result = metrics(ranks, [d[0] for d in docs], 5)
        result |= {
            "chars": size,
            "chunks": await db.fetchval("SELECT count(*) FROM chunks"),
            "ms_po_upitu": round((time.perf_counter() - start) * 1000 / len(docs), 2),
        }
        results.append(result)
        assert result["recall_at_k"] == 1
        assert (
            await db.fetchval("SELECT content_text FROM documents WHERE id=$1", docs[0][0])
            == docs[0][2]
        )
        assert (await reindex_all())["preskoceno"] == len(docs)
    print("F2.3 test eval:", json.dumps(results))
    original = await db.fetchval("SELECT content_hash FROM documents WHERE id=$1", docs[0][0])
    monkeypatch.setattr(cfg, "chunk_chars", 600)
    monkeypatch.setattr(store, "embed", AsyncMock(side_effect=RuntimeError("Prekid")))
    with pytest.raises(RuntimeError):
        await reindex_all()
    assert (
        await db.fetchval("SELECT content_hash FROM documents WHERE id=$1", docs[0][0]) == original
    )
    await db.execute("UPDATE documents SET content_text=NULL WHERE id=$1", docs[0][0])
    with pytest.raises(ValueError, match="Nedostaje izvorni tekst"):
        await reindex_all()


async def test_rerank_evaluation_top_twenty_cost_and_fallback(db, monkeypatch):
    import json
    import time

    from apu import llm
    from apu.config import settings
    from apu.rag import store
    from evals.rag_eval import metrics

    for i in range(24):
        await store.upsert_document(f"test:{i}", "test", f"Ponuda {i}", "Ponuda za projekat i rok.")
    start = time.perf_counter()
    baseline = await store.search("ponuda projekat", limit=20)
    before_ms = (time.perf_counter() - start) * 1000
    expected = baseline[7].document_id
    before = metrics([[h.document_id for h in baseline]], [expected], 5)

    async def create(**kwargs):
        payload = json.loads(kwargs["messages"][0]["content"])
        assert len(payload["odlomci"]) == 20
        target = next(
            i for i, h in enumerate(payload["odlomci"]) if h["naslov"] == baseline[7].title
        )
        await asyncio.sleep(0.015)
        return SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="text", text=json.dumps([target] + [i for i in range(20) if i != target])
                )
            ],
            stop_reason="end_turn",
            usage=SimpleNamespace(
                input_tokens=1000,
                output_tokens=50,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )

    model = AsyncMock(side_effect=create)
    monkeypatch.setattr(
        llm, "client", lambda: SimpleNamespace(messages=SimpleNamespace(create=model))
    )
    monkeypatch.setattr(settings(), "rerank", "on")
    start = time.perf_counter()
    ranked = await store.search("ponuda projekat", limit=5)
    after_ms = (time.perf_counter() - start) * 1000
    after = metrics([[h.document_id for h in ranked]], [expected], 5)
    assert len(ranked) == 5 and ranked[0].document_id == expected
    assert before["recall_at_k"] == 0 and after["recall_at_k"] == after["mrr"] == 1
    cost = float(await db.fetchval("SELECT sum(cost_usd) FROM usage WHERE purpose='rerank'"))
    assert cost > 0
    print(
        "F2.4 test eval:",
        json.dumps(
            {
                "pre": before,
                "posle": after,
                "ms_pre": round(before_ms, 2),
                "ms_posle": round(after_ms, 2),
                "cost_usd": cost,
            }
        ),
    )
    model.side_effect = RuntimeError("Nedostupan model")
    fallback = await store.search("ponuda projekat", limit=5)
    assert [h.document_id for h in fallback] == [h.document_id for h in baseline[:5]]
    monkeypatch.setattr(settings(), "rerank", "off")
    model.reset_mock()
    await store.search("ponuda projekat")
    model.assert_not_awaited()


async def test_relevance_threshold_calibration(db, monkeypatch):
    import json
    import time

    from apu.config import settings
    from apu.rag import store
    from evals.rag_eval import metrics

    def vector(parts):
        v = [0.0] * 1536
        for i, value in parts.items():
            v[i] = value
        v[10] = math.sqrt(max(0, 1 - sum(x * x for x in v)))
        return v

    async def embed(texts, kind="passage"):
        return [
            vector({0 if "Razvoj" in text else 1 if "Odsustvo" in text else 2: 1}) for text in texts
        ]

    queries = {
        "Novi portal": ({0: 0.8}, "test:razvoj"),
        "Koliki je predah": ({1: 0.4}, "test:odmor"),
        "108073515": ({2: 0.01}, "test:racun"),
        "Kako popraviti kosilicu": ({0: 0.2, 1: 0.2, 2: 0.2}, None),
        "Recept za palačinke": ({}, None),
    }

    async def embed_one(text, kind="query"):
        return vector(queries[text][0])

    monkeypatch.setattr(store, "embed", embed)
    monkeypatch.setattr(store, "embed_one", embed_one)
    for name, text in (
        ("razvoj", "Razvoj internet prezentacija."),
        ("odmor", "Odsustvo zaposlenih traje dvadeset radnih dana."),
        ("racun", "Račun firme, PIB 108073515."),
    ):
        await store.upsert_document(f"test:{name}", "test", name, text)
    results = []
    for threshold in (0, 0.15, 0.3, 0.45):
        monkeypatch.setattr(settings(), "rag_min_similarity", threshold)
        start = time.perf_counter()
        ranked = [[h.document_id for h in await store.search(q)] for q in queries]
        result = metrics(ranked, [value[1] for value in queries.values()], 5)
        result |= {
            "threshold": threshold,
            "ms_po_upitu": round((time.perf_counter() - start) * 1000 / len(queries), 2),
        }
        results.append(result)
    print("F2.5 test eval:", json.dumps(results))
    assert results[0]["recall_at_k"] == results[2]["recall_at_k"] == 1
    assert results[0]["precision"] == 0.6 and results[2]["precision"] == 1
    assert results[0]["negative_accuracy"] == 0 and results[2]["negative_accuracy"] == 1
    assert results[3]["recall_at_k"] < results[2]["recall_at_k"]
    monkeypatch.setattr(settings(), "rag_min_similarity", 1)
    hits = await store.search("108073515")
    assert len(hits) == 1 and hits[0].keyword_rank == 1
    assert hits[0].similarity < 0.1


async def test_date_filter_evaluation_applies_before_candidate_limits(db):
    import json
    import time
    from datetime import date, datetime

    from apu.rag import store
    from evals.rag_eval import metrics

    for i in range(35):
        await store.upsert_document(
            f"test:stari:{i}",
            "test",
            "Orion",
            "Orion " * 50,
            modified_at=datetime.fromisoformat("2026-08-15T12:00:00+00:00"),
        )
    await store.upsert_document(
        "test:septembar",
        "test",
        "Orion septembar",
        "Orion: u septembru je Marko potvrdio rok i budžet projekta.",
        modified_at=datetime.fromisoformat("2026-09-30T21:59:00+00:00"),
    )
    await store.upsert_document(
        "test:oktobar",
        "test",
        "Orion oktobar",
        "Orion " * 60,
        modified_at=datetime.fromisoformat("2026-09-30T22:00:00+00:00"),
    )
    await store.upsert_document("test:nepoznat", "test", "Orion bez datuma", "Orion " * 60)
    start = time.perf_counter()
    before = metrics(
        [[h.document_id for h in await store.search("Orion", limit=5)]], ["test:septembar"], 5
    )
    before["ms_po_upitu"] = round((time.perf_counter() - start) * 1000, 2)
    start = time.perf_counter()
    hits = await store.search(
        "Orion", limit=5, date_from=date(2026, 9, 1), date_to=date(2026, 9, 30)
    )
    after = metrics([[h.document_id for h in hits]], ["test:septembar"], 5)
    after["ms_po_upitu"] = round((time.perf_counter() - start) * 1000, 2)
    assert before["recall_at_k"] == 0 and after["recall_at_k"] == after["mrr"] == 1
    assert [h.document_id for h in hits] == ["test:septembar"]
    print("F2.6 test eval:", json.dumps({"pre": before, "posle": after, "dokumenata": 38}))


async def test_date_filter_boundaries_open_ranges_unknown_dates_and_dst(db, monkeypatch):
    from datetime import date, datetime

    from apu.config import settings
    from apu.rag import store

    stamps = {
        "pre": "2026-08-31T21:59:59+00:00",
        "od": "2026-08-31T22:00:00+00:00",
        "do": "2026-09-30T21:59:59.999999+00:00",
        "posle": "2026-09-30T22:00:00+00:00",
        "dst-pocetak": "2026-10-24T22:00:00+00:00",
        "dst-kraj": "2026-10-25T22:59:59+00:00",
        "dst-posle": "2026-10-25T23:00:00+00:00",
    }
    for key, stamp in stamps.items():
        await store.upsert_document(
            key, "test", "Period", "Period za proveru.", modified_at=datetime.fromisoformat(stamp)
        )
    await store.upsert_document("bez-datuma", "test", "Period", "Period za proveru.")
    await store.upsert_document(
        "drugi-izvor",
        "drugi",
        "Period",
        "Period za proveru.",
        modified_at=datetime.fromisoformat(stamps["od"]),
    )

    async def ids(**kwargs):
        return {
            h.document_id for h in await store.search("Period", limit=15, source="test", **kwargs)
        }

    assert await ids(date_from=date(2026, 9, 1), date_to=date(2026, 9, 30)) == {"od", "do"}
    assert await ids(date_to=date(2026, 9, 30)) == {"pre", "od", "do"}
    assert "bez-datuma" in await ids()
    assert "bez-datuma" not in await ids(date_from=date(2026, 9, 1))
    assert await ids(date_from=date(2026, 10, 25), date_to=date(2026, 10, 25)) == {
        "dst-pocetak",
        "dst-kraj",
    }
    # I opcioni model vidi samo kandidate koji su već prošli filter.
    from apu.rag import rerank

    reorder = AsyncMock(side_effect=lambda query, hits: hits)
    monkeypatch.setattr(rerank, "rerank", reorder)
    monkeypatch.setattr(settings(), "rerank", "on")
    assert await ids(date_from=date(2026, 9, 1), date_to=date(2026, 9, 30)) == {"od", "do"}
    assert {h.document_id for h in reorder.await_args.args[1]} == {"od", "do"}
    embed = AsyncMock()
    monkeypatch.setattr(store, "embed_one", embed)
    with pytest.raises(ValueError, match="Datum od"):
        await store.search("Period", date_from=date(2026, 10, 1), date_to=date(2026, 9, 1))
    embed.assert_not_awaited()


async def test_metadata_only_updates_and_rechunk_preserve_source_date(db, monkeypatch):
    from datetime import datetime

    from apu.config import settings
    from apu.rag import store
    from scripts.reindex_all import reindex_all

    stamp = datetime.fromisoformat("2026-09-15T12:00:00+00:00")
    await store.upsert_document(
        "test:meta", "test", "Metapodaci", "Dugačak tekst. " * 200, modified_at=stamp
    )
    old_ids = await db.fetch("SELECT id FROM chunks ORDER BY id")
    embed = AsyncMock(wraps=store.embed)
    monkeypatch.setattr(store, "embed", embed)
    later = datetime.fromisoformat("2026-10-01T12:00:00+00:00")
    assert (
        await store.upsert_document(
            "test:meta",
            "test",
            "Metapodaci",
            "Dugačak tekst. " * 200,
            "https://example.com",
            modified_at=later,
        )
        == 0
    )
    embed.assert_not_awaited()
    assert await db.fetch("SELECT id FROM chunks ORDER BY id") == old_ids
    assert await db.fetchval("SELECT modified_at FROM documents") == later
    monkeypatch.setattr(settings(), "chunk_chars", 600)
    await reindex_all()
    assert await db.fetchval("SELECT modified_at FROM documents") == later
    assert await db.fetchval("SELECT url FROM documents") == "https://example.com"
    # Datum razgovora iz ID-ja može se obnoviti i kada je sirova istorija već obrisana.
    await store.upsert_document(
        "razgovor:2026-09-15", "razgovor", "Sažetak", "Dogovor u septembru."
    )
    await reindex_all("razgovor")
    restored = await db.fetchval("SELECT modified_at FROM documents WHERE source='razgovor'")
    assert restored.isoformat() == "2026-09-14T22:00:00+00:00"


async def test_cost_benchmark_cache_comparison_and_isolation(db, monkeypatch):
    from pathlib import Path

    from apu.config import settings
    from evals.cost_bench import benchmark, read_prompts

    rows = read_prompts(Path("evals/prompts.jsonl"))
    reports = []
    for mode in ("off", "on"):
        monkeypatch.setattr(settings(), "prompt_cache", mode)
        reports.append(await benchmark(rows, simulation=True))
    assert reports[0]["poruka"] == reports[1]["poruka"] == 50
    assert (
        reports[0]["poziva"] == reports[1]["poziva"] == 60 + max(0, 49 - settings().history_turns)
    )
    assert reports[0]["cache_percent"] == 0 < reports[1]["cache_percent"]
    assert reports[0]["cost_usd"] > reports[1]["cost_usd"]
    assert reports[1]["cost_by_purpose"]["history_summary"] > 0
    assert await db.fetchval("SELECT count(*) FROM messages") == 0
    assert await db.fetchval("SELECT count(*) FROM facts") == 0
    print("F3.1 test eval:", reports)


async def test_router_evaluation_tracks_accuracy_cost_and_confusion(db):
    from evals.router_eval import evaluate

    reports = await evaluate(simulation=True)
    assert reports[0]["n"] == reports[1]["n"] == 40
    assert reports[1]["tačnost"] == 1 > reports[0]["tačnost"]
    assert reports[0]["trošak_izbora_usd"] == 0 < reports[1]["trošak_izbora_usd"]
    assert await db.fetchval("SELECT count(*) FROM usage WHERE purpose='router'") == 38
    print("F3.2 test eval:", reports)


async def test_streaming_agent_keeps_tool_flow_and_history(db, monkeypatch):
    from anthropic.types import Message

    from apu import llm, memory
    from apu.agent import history, loop

    monkeypatch.setattr(memory, "extract_and_save", AsyncMock())
    calls = []

    async def stream(*, on_text, **kwargs):
        calls.append(kwargs)
        first = len(calls) == 1
        await on_text("Proveravam." if first else "Gotovo.")
        content = (
            [{"type": "tool_use", "id": "s1", "name": "memory_list", "input": {}}]
            if first
            else [{"type": "text", "text": "Gotovo."}]
        )
        return Message.model_validate(
            {
                "id": "stream",
                "type": "message",
                "role": "assistant",
                "model": kwargs["model"],
                "content": content,
                "stop_reason": "tool_use" if first else "end_turn",
                "usage": {"input_tokens": 100, "output_tokens": 20},
            }
        )

    monkeypatch.setattr(llm, "stream", stream)
    result = await loop.run(7, "Šta pamtiš?", on_text=AsyncMock())
    assert result.text == "Gotovo." and len(calls) == 2
    assert calls[1]["messages"][-1]["content"][0]["tool_use_id"] == "s1"
    saved = await history.load(7, 12)
    assert [m["role"] for m in saved] == ["user", "assistant", "user", "assistant"]
    assert "cache_control" not in str(saved)


async def test_daily_budget_warns_once_forces_fast_and_resets_at_local_midnight(db, monkeypatch):
    from datetime import datetime
    from decimal import Decimal
    from zoneinfo import ZoneInfo

    from apu import budget, llm
    from apu.config import settings

    now = [datetime(2026, 10, 17, 23, 50, tzinfo=ZoneInfo("Europe/Belgrade"))]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now[0].astimezone(tz)

    monkeypatch.setattr(budget, "datetime", Clock)
    monkeypatch.setattr(settings(), "daily_budget_usd", Decimal("1"))
    bot = SimpleNamespace(send_message=AsyncMock())
    monkeypatch.setattr(budget, "_bot", bot)

    async def cost(value, stamp=None):
        await db.execute(
            """INSERT INTO usage (model,purpose,input_tokens,output_tokens,cost_usd,latency_ms,created_at)
                            VALUES ('test','budget',0,0,$1,0,$2)""",
            Decimal(value),
            stamp or now[0],
        )

    await cost("10", datetime.fromisoformat("2026-10-16T21:59:59+00:00"))
    await cost("0.79")
    assert await budget.model_for(settings().model_deep) == settings().model_deep
    bot.send_message.assert_not_awaited()
    await cost("0.01")
    await asyncio.gather(*(budget.model_for(settings().model_main) for _ in range(5)))
    assert bot.send_message.await_count == 1 and "80%" in bot.send_message.await_args.args[1]
    await cost("0.20")
    assert await budget.model_for(settings().model_deep) == settings().model_fast
    assert bot.send_message.await_count == 2 and "100%" in bot.send_message.await_args.args[1]
    # Restarti ne ponavljaju obaveštenje jer je stanje u bazi.
    bot.send_message.reset_mock()
    assert await budget.model_for(settings().model_main) == settings().model_fast
    bot.send_message.assert_not_awaited()
    create = AsyncMock(
        return_value=SimpleNamespace(usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    )
    monkeypatch.setattr(
        llm, "client", lambda: SimpleNamespace(messages=SimpleNamespace(create=create))
    )
    await llm.create(purpose="budget_test", model=settings().model_deep)
    assert create.await_args.kwargs["model"] == settings().model_fast
    now[0] = datetime(2026, 10, 18, 0, 0, tzinfo=ZoneInfo("Europe/Belgrade"))
    assert await budget.model_for(settings().model_deep) == settings().model_deep
    assert (await budget.snapshot())[1] == 0


async def test_budget_notification_failure_retries_and_record_triggers_warning(db, monkeypatch):
    from decimal import Decimal

    from apu import budget, usage
    from apu.config import settings

    monkeypatch.setattr(settings(), "daily_budget_usd", Decimal("1"))
    bot = SimpleNamespace(send_message=AsyncMock(side_effect=RuntimeError("Telegram")))
    monkeypatch.setattr(budget, "_bot", bot)
    await usage.record(usage.Usage(settings().model_main, 400000, 0), "budget_test", 0)
    assert await db.fetchval("SELECT count(*) FROM kv_state") == 0
    bot.send_message.side_effect = None
    assert await budget.model_for(settings().model_main) == settings().model_main
    assert bot.send_message.await_count == 2
    assert await db.fetchval("SELECT count(*) FROM kv_state") == 1


async def test_running_summary_keeps_complete_turns_and_incremental_context(db, monkeypatch):
    from anthropic.types import Message

    from apu import llm, memory
    from apu.agent import history, loop, summary
    from apu.config import settings

    monkeypatch.setattr(settings(), "history_turns", 2)
    monkeypatch.setattr(memory, "extract_and_save", AsyncMock())
    original = [
        {"role": "user", "content": "Orion: rok je petak, vlasnik je Marko."},
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "name": "memory_list", "id": "old", "input": {}}],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "old", "content": "Nema dodatnih podataka."}
            ],
        },
        {"role": "assistant", "content": "Dogovor ostaje."},
        {"role": "user", "content": "Ponudu samo pripremi, bez slanja."},
        {"role": "assistant", "content": "Nacrt čeka potvrdu."},
        {"role": "user", "content": "Treća tema."},
        {"role": "assistant", "content": "Treći odgovor."},
        {"role": "user", "content": "Četvrta tema."},
        {"role": "assistant", "content": "Četvrti odgovor."},
    ]
    await history.append(1, original)
    calls = []

    async def create(*, purpose, **kwargs):
        calls.append((purpose, kwargs))
        text = (
            "Орион: рок петак, Марко. Понуда је нацрт и чека потврду."
            if purpose == "history_summary"
            else "Orion ima rok u petak."
        )
        return Message.model_validate(
            {
                "id": "context",
                "type": "message",
                "role": "assistant",
                "model": kwargs["model"],
                "content": [{"type": "text", "text": text}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 100, "output_tokens": 20},
            }
        )

    monkeypatch.setattr(llm, "create", create)
    recent, text = await summary.load_context(1, 2)
    assert len(recent) == 4 and recent[0]["content"] == "Treća tema."
    assert text.startswith("Orion:") and "nacrt" in text
    assert "tool_use_id" in calls[0][1]["messages"][0]["content"]
    assert await db.fetchval("SELECT count(*) FROM messages") == len(original)
    await summary.load_context(1, 2)
    assert len(calls) == 1
    await loop.run(1, "Koji je rok za Orion?")
    chat = calls[-1][1]
    assert text in chat["messages"][-1]["content"][0]["text"]
    assert text not in str(chat["system"])
    saved = await db.fetchval(
        "SELECT content FROM messages WHERE chat_id=1 AND role='user' ORDER BY id DESC LIMIT 1"
    )
    assert text not in saved[0]["text"]
    # Sledeća poruka sažima samo novu ispalu razmenu, uz prethodni sažetak.
    await summary.load_context(1, 2)
    last = calls[-1][1]["messages"][0]["content"]
    assert "Treća tema." in last and "prethodni_sažetak" in last and "Orion:" in last
    assert "rok je petak, vlasnik" not in last
    await history.clear(1)
    assert await db.fetchval("SELECT count(*) FROM conversation_context") == 0


async def test_summary_failure_preserves_progress_and_raw_history(db, monkeypatch):
    from types import SimpleNamespace

    from apu.agent import history, summary

    messages = [
        {"role": role, "content": f"{i} {role}"} for i in range(4) for role in ("user", "assistant")
    ]
    await history.append(1, messages)
    good = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="Sažetak.")], stop_reason="end_turn"
    )
    create = AsyncMock(return_value=good)
    monkeypatch.setattr(summary.llm, "create", create)
    await summary.load_context(1, 2)
    state = await db.fetchrow("SELECT * FROM conversation_context")
    await history.append(
        1, [{"role": "user", "content": "Nova tema"}, {"role": "assistant", "content": "Odgovor"}]
    )
    create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="Nepotpuno")], stop_reason="max_tokens"
    )
    with pytest.raises(RuntimeError, match="nije potpun"):
        await summary.load_context(1, 2)
    assert await db.fetchrow("SELECT * FROM conversation_context") == state
    assert await db.fetchval("SELECT count(*) FROM messages") == len(messages) + 2
    create.return_value = good
    await summary.load_context(1, 2)
    assert await db.fetchval("SELECT through_id FROM conversation_context") > state["through_id"]


async def test_reset_during_summarization_does_not_restore_deleted_context(db, monkeypatch):
    from types import SimpleNamespace

    from apu.agent import history, summary

    await history.append(
        1, [{"role": r, "content": str(i)} for i in range(3) for r in ("user", "assistant")]
    )
    entered, release = asyncio.Event(), asyncio.Event()

    async def create(**kwargs):
        entered.set()
        await release.wait()
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="Stari sažetak")], stop_reason="end_turn"
        )

    monkeypatch.setattr(summary.llm, "create", create)
    task = asyncio.create_task(summary.load_context(1, 1))
    await entered.wait()
    await history.clear(1)
    release.set()
    with pytest.raises(RuntimeError, match="Istorija je promenjena"):
        await task
    assert await db.fetchval("SELECT count(*) FROM conversation_context") == 0


async def test_long_history_summary_reads_all_parts_before_advancing(db, monkeypatch):
    from types import SimpleNamespace

    from apu.agent import history, summary

    await history.append(
        1,
        [
            {
                "role": "user",
                "content": "POČETAK " + "Dugačka rasprava o sajtu. " * 1800 + " KRAJNJI_DOGOVOR",
            },
            {"role": "assistant", "content": "Odgovor na dugu raspravu."},
            {"role": "user", "content": "Sledeća tema."},
            {"role": "assistant", "content": "Nov odgovor."},
        ],
    )
    calls = []

    async def create(**kwargs):
        calls.append(kwargs["messages"][0]["content"])
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=f"Sažetak dela {len(calls)}.")],
            stop_reason="end_turn",
        )

    monkeypatch.setattr(summary.llm, "create", create)
    recent, _text = await summary.load_context(1, 1)
    assert len(calls) >= 3 and len(recent) == 2
    assert "POČETAK" in calls[0] and any("KRAJNJI_DOGOVOR" in c for c in calls)
    assert "Sažetak dela 1." in calls[1]
    assert await db.fetchval("SELECT through_id FROM conversation_context") == 2
    assert await db.fetchval("SELECT count(*) FROM messages") == 4


async def test_reembed_changes_both_vector_dimensions_atomically(migration_conn, monkeypatch):
    from apu import db as dbmod
    from apu.config import settings
    from scripts import reembed

    conn = migration_conn
    await dbmod.migrate(conn, 1536)
    await dbmod._init_conn(conn)
    await conn.execute(
        "INSERT INTO documents(id,source,title,content_hash,index_fingerprint) VALUES ('d','test','Naslov','hash','v2:1200:200:openai:1536')"
    )
    await conn.execute(
        "INSERT INTO chunks(document_id,ord,text,embedding) VALUES ('d',0,'Sačuvani deo',$1)",
        fake_vector("Sačuvani deo"),
    )
    await conn.execute(
        "INSERT INTO facts(text,category,embedding) VALUES ('Marko je knjigovođa','osoba',$1)",
        fake_vector("Marko"),
    )
    monkeypatch.setattr(settings(), "embed_provider", "local")

    async def embed(texts, kind="passage"):
        assert kind == "passage"
        return [fake_vector(t, 384) for t in texts]

    monkeypatch.setattr(reembed.embeddings, "embed", embed)
    result = await reembed.reembed(conn)
    assert result["delova"] == result["činjenica"] == 1 and result["dimenzija"] == 384
    assert await conn.fetchval("SELECT vector_dims(embedding) FROM chunks") == 384
    assert await conn.fetchval("SELECT vector_dims(embedding) FROM facts") == 384
    assert await conn.fetchval("SELECT text FROM chunks") == "Sačuvani deo"
    assert await conn.fetchval("SELECT content_hash FROM documents") == "hash"
    assert "v3:1200:200:local:" in await conn.fetchval("SELECT index_fingerprint FROM documents")
    await dbmod.check_embedding_space(conn)
    monkeypatch.setattr(settings(), "embed_provider", "openai")
    with pytest.raises(RuntimeError, match=r"scripts.reembed"):
        await dbmod.check_embedding_space(conn)

    async def restore(texts, kind="passage"):
        return [fake_vector(t) for t in texts]

    monkeypatch.setattr(reembed.embeddings, "embed", restore)
    await conn.execute("UPDATE documents SET index_fingerprint='v2:neispravno:200:local:384'")
    with pytest.raises(ValueError):
        await reembed.reembed(conn)
    assert await conn.fetchval("SELECT vector_dims(embedding) FROM chunks") == 384
    assert await conn.fetchval("SELECT to_regclass('chunks_embedding_idx')")
    await conn.execute("UPDATE documents SET index_fingerprint='v2:1200:200:local:384'")

    async def failure(texts, kind="passage"):
        raise RuntimeError("Prekid embeddinga")

    monkeypatch.setattr(reembed.embeddings, "embed", failure)
    with pytest.raises(RuntimeError):
        await reembed.reembed(conn)
    assert await conn.fetchval("SELECT dimensions FROM embedding_space") == 384
    assert await conn.fetchval("SELECT vector_dims(embedding) FROM facts") == 384

    monkeypatch.setattr(reembed.embeddings, "embed", restore)
    await reembed.reembed(conn)
    await dbmod.check_embedding_space(conn)
    assert await conn.fetchval("SELECT vector_dims(embedding) FROM chunks") == 1536


async def test_embedding_benchmark_three_models_uses_same_corpus_and_reports_cost(
    db, monkeypatch, respx_mock
):
    import json
    from types import SimpleNamespace

    from apu.config import settings
    from apu.rag import embed, store
    from evals.embedding_bench import benchmark
    from scripts.reembed import reembed

    monkeypatch.setattr(settings(), "openai_api_key", "test")
    monkeypatch.setattr(store, "embed", embed.embed)
    monkeypatch.setattr(store, "embed_one", embed.embed_one)

    def api(request):
        texts = json.loads(request.content)["input"]
        return httpx.Response(
            200,
            json={
                "data": [{"index": i, "embedding": fake_vector(t)} for i, t in enumerate(texts)],
                "usage": {"total_tokens": len(texts) * 10},
            },
        )

    respx_mock.post("https://api.openai.com/v1/embeddings").mock(side_effect=api)

    class Local:
        def __init__(self, name):
            self.dim = 384 if name.endswith("-small") else 768

        def encode(self, texts, **kwargs):
            return [SimpleNamespace(tolist=lambda t=t: fake_vector(t, self.dim)) for t in texts]

    monkeypatch.setattr(embed, "_local_model", Local)
    corpus = {
        "documents": [
            {"id": "a", "title": "Orion", "text": "Orion razvoj sajta."},
            {"id": "b", "title": "Atlas", "text": "Atlas hosting."},
        ],
        "questions": [{"pitanje": "Orion", "dokument": "a"}, {"pitanje": "Atlas", "dokument": "b"}],
    }
    try:
        reports = await benchmark(corpus, ["openai", "small", "base"], price_per_million="0.02")
        assert [r["dimensions"] for r in reports] == [1536, 384, 768]
        assert len({r["korpus_sha256"] for r in reports}) == 1
        assert all(r["recall_at_k"] == 1 for r in reports)
        assert reports[0]["api_usd"] > 0 and reports[1]["api_usd"] == reports[2]["api_usd"] == 0
    finally:
        async with db.acquire() as conn:
            await reembed(conn)

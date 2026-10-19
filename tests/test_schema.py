"""Provera šema čita stvarni Notion SDK preko respx, bez privatnih naloga."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from telegram.ext import Application

from dexter import main, telegram_bot
from dexter.config import settings
from dexter.services import schema

BASE = "https://api.notion.com/v1"
ROOT = "11111111-1111-1111-1111-111111111111"
SOURCE = "22222222-2222-2222-2222-222222222222"
FIELDS = ("tasks", "clients", "birthdays", "invoices", "checklist", "dnevnik", "todo")


@pytest.fixture
def schema_api(monkeypatch, respx_mock):
    cfg = settings()
    monkeypatch.setattr(cfg, "notion_api_key", "test-key")
    for field in FIELDS:
        monkeypatch.setattr(cfg, f"notion_{field}_db_id", None)
    monkeypatch.setattr(cfg, "notion_tasks_db_id", ROOT)
    database = respx_mock.get(f"{BASE}/databases/{ROOT}").respond(
        200, json={"data_sources": [{"id": SOURCE}]}
    )
    source = respx_mock.get(f"{BASE}/data_sources/{SOURCE}").respond(
        200, json={"properties": {"Name": {"type": "title"}, "Status": {"type": "status"}}}
    )
    return SimpleNamespace(database=database, source=source, cfg=cfg)


def test_expected_preserves_all_seven_v1_contracts_and_dynamic_habits(schema_api, monkeypatch):
    for field in FIELDS:
        monkeypatch.setattr(schema_api.cfg, f"notion_{field}_db_id", ROOT)
    monkeypatch.setattr(schema_api.cfg, "checklist_pozitivne", "Trening, Doručak")
    monkeypatch.setattr(schema_api.cfg, "checklist_izbegavanja", "Bez slatkog")
    monkeypatch.setattr(schema_api.cfg, "checklist_ciljna_stavka", "Trening")
    bases = {base.name: base for base in schema.expected()}
    assert len(bases) == 7
    assert bases["TASK BOARD"].columns == {"Name": "title", "Status": "status"}
    assert bases["KLIJENTI"].columns == {"Klijent": "title", "Domen": "url", "Aktivan": "select"}
    assert bases["Rođendani"].columns == {"Ime i prezime": "title", "Rođendan": "date"}
    assert bases["FAKTURE"].columns == {
        "Broj": "title",
        "Datum izdavanja": "date",
        "Datum prometa": "date",
        "Iznos": "number",
        "Status": "select",
    }
    assert bases["Dnevna checklista"].columns == {
        "Dan": "title",
        "Datum": "date",
        "Trening": "checkbox",
        "Doručak": "checkbox",
        "Bez slatkog": "checkbox",
    }
    assert bases["Dnevna checklista"].filter_column == "Trening"
    assert bases["Dnevnik"].columns == {
        "Dan": "title",
        "Datum": "date",
        "Raspoloženje": "select",
        "Energija": "select",
        "Ključna reč": "rich_text",
        "Checklista": "relation",
    }
    assert bases["To-do lista"].columns == {"Zadatak": "title", "Status": "status", "Rok": "date"}
    assert "PIB" not in bases["KLIJENTI"].columns
    assert "Klijent" not in bases["FAKTURE"].columns


@pytest.mark.parametrize("with_key,with_id", [(False, True), (True, False)])
async def test_unconfigured_schema_uses_no_network(schema_api, monkeypatch, with_key, with_id):
    if not with_key:
        monkeypatch.setattr(schema_api.cfg, "notion_api_key", None)
    if not with_id:
        monkeypatch.setattr(schema_api.cfg, "notion_tasks_db_id", None)
    result = await schema.check()
    assert result == {"provereno": 0, "nalazi": [], "ok": True}
    assert "Nijedna Notion baza" in schema.format_report(result)
    assert not schema_api.database.called


async def test_matching_schema_reads_data_source_and_never_reads_or_writes_rows(
    schema_api, respx_mock
):
    result = await schema.check()
    assert result == {"provereno": 1, "nalazi": [], "ok": True}
    assert "provereno baza: 1" in schema.format_report(result)
    assert schema_api.source.calls[0].request.headers["Notion-Version"] == "2025-09-03"
    assert len(respx_mock.calls) == 2
    assert all(call.request.method == "GET" for call in respx_mock.calls)


async def test_missing_and_wrong_type_are_reported_without_mutation(schema_api):
    schema_api.source.respond(200, json={"properties": {"Name": {"type": "rich_text"}}})
    result = await schema.check()
    finding = result["nalazi"][0]
    assert not result["ok"]
    assert finding["fale"] == [{"ime": "Status", "uFilteru": False}]
    assert finding["pogresanTip"] == [{"ime": "Name", "ocekivano": "title", "nadjeno": "rich_text"}]
    assert "Nema kolone „Status”" in schema.format_report(result)


@pytest.mark.parametrize("count", [0, 2])
async def test_zero_or_multiple_data_sources_are_not_arbitrarily_selected(schema_api, count):
    schema_api.database.respond(200, json={"data_sources": [{"id": SOURCE}] * count})
    result = await schema.check()
    assert not result["ok"] and "tačno jedan" in result["nalazi"][0]["nedostupna"]
    assert not schema_api.source.called


async def test_absent_properties_is_unavailable_not_missing_all_columns(schema_api):
    schema_api.source.respond(200, json={"id": SOURCE})
    result = await schema.check()
    assert "šemu kolona" in result["nalazi"][0]["nedostupna"]


@pytest.mark.parametrize("status", [401, 403, 404, 400])
async def test_notion_failure_is_actionable_and_does_not_expose_response_secrets(
    schema_api, status
):
    schema_api.database.respond(
        status,
        json={
            "object": "error",
            "status": status,
            "code": "restricted_resource",
            "message": "TAJNA test-key https://privatno",
        },
    )
    result = await schema.check()
    text = schema.format_report(result)
    assert not result["ok"] and "Nedostupna" in text
    assert not any(secret in text for secret in ("TAJNA", "test-key", "privatno"))


async def test_per_base_timeout_is_a_finding(schema_api, monkeypatch):
    async def slow(request):
        await asyncio.Event().wait()

    schema_api.database.mock(side_effect=slow)
    monkeypatch.setattr(schema, "CHECK_TIMEOUT", 0)
    result = await schema.check()
    assert not result["ok"] and "Isteklo" in result["nalazi"][0]["nedostupna"]


async def test_cancel_is_propagated(schema_api, monkeypatch):
    monkeypatch.setattr(schema, "compare", Mock(side_effect=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await schema.check()


async def test_one_unavailable_base_does_not_hide_other_findings(
    schema_api, monkeypatch, respx_mock
):
    monkeypatch.setattr(schema_api.cfg, "notion_clients_db_id", SOURCE)
    schema_api.database.respond(
        403,
        json={
            "object": "error",
            "status": 403,
            "code": "restricted_resource",
            "message": "Ne može",
        },
    )
    respx_mock.get(f"{BASE}/databases/{SOURCE}").respond(200, json={"data_sources": [{"id": ROOT}]})
    respx_mock.get(f"{BASE}/data_sources/{ROOT}").respond(200, json={"properties": {}})
    result = await schema.check()
    assert result["provereno"] == 2 and len(result["nalazi"]) == 2
    assert result["nalazi"][1]["baza"] == "KLIJENTI"


def test_untracked_checkboxes_and_critical_filter_are_distinct():
    base = schema.ExpectedBase(
        "Checklista", ROOT, {"Trening": "checkbox", "Doručak": "checkbox"}, "checkbox", "Trening"
    )
    result = schema.compare(
        base,
        {
            "Doručak": {"type": "checkbox"},
            "Додатно": {"type": "checkbox"},
            "Formula": {"type": "formula"},
        },
    )
    assert result["fale"] == [{"ime": "Trening", "uFilteru": True}]
    assert result["nepracene"] == ["Додатно"]
    text = schema.format_report({"provereno": 1, "nalazi": [result], "ok": False})
    assert "filteru nedeljnog cilja" in text and "Dodatno" in text and "Додатно" not in text
    assert "Formula" not in text


@pytest.mark.parametrize("positive,target", [("A, A", "A"), (" ", "A"), ("A", "B")])
def test_bad_habit_configuration_is_a_local_finding(schema_api, monkeypatch, positive, target):
    monkeypatch.setattr(schema_api.cfg, "notion_checklist_db_id", ROOT)
    monkeypatch.setattr(schema_api.cfg, "checklist_pozitivne", positive)
    monkeypatch.setattr(schema_api.cfg, "checklist_izbegavanja", "")
    monkeypatch.setattr(schema_api.cfg, "checklist_ciljna_stavka", target)
    base = next(b for b in schema.expected() if b.name == "Dnevna checklista")
    assert base.configuration
    assert schema.compare(base, {name: {"type": kind} for name, kind in base.columns.items()})[
        "podesavanja"
    ]


def test_diary_without_checklist_does_not_require_relation(schema_api, monkeypatch):
    monkeypatch.setattr(schema_api.cfg, "notion_dnevnik_db_id", ROOT)
    assert "Checklista" not in schema.expected()[-1].columns


def test_parts_preserves_all_text_and_telegram_utf16_limit():
    text = "Распоред 🧠\n" * 3000
    chunks = list(schema.parts(text))
    assert len(chunks) > 1
    assert all(len(part.encode("utf-16-le")) // 2 <= 3900 for part in chunks)
    assert "".join(chunks) == "Raspored 🧠\n" * 3000


async def test_schema_command_is_owner_only_latin_and_chunked(monkeypatch):
    check = AsyncMock(return_value={"provereno": 1, "nalazi": [], "ok": True})
    monkeypatch.setattr(schema, "check", check)
    monkeypatch.setattr(schema, "format_report", lambda result: "Провера 🧠 " * 1000)
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=999), message=message)
    await telegram_bot.cmd_schema(update, None)
    check.assert_not_awaited()
    update.effective_chat.id = 1
    await telegram_bot.cmd_schema(update, None)
    assert message.reply_text.await_count > 1
    assert (
        "".join(call.args[0] for call in message.reply_text.call_args_list) == "Provera 🧠 " * 1000
    )


async def test_schema_command_unexpected_failure_is_safe(monkeypatch):
    monkeypatch.setattr(schema, "check", AsyncMock(side_effect=RuntimeError("TAJNA")))
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=1), message=SimpleNamespace(reply_text=AsyncMock())
    )
    await telegram_bot.cmd_schema(update, None)
    assert "TAJNA" not in update.message.reply_text.call_args.args[0]
    assert "Nisam uspeo" in update.message.reply_text.call_args.args[0]


def test_schema_command_is_registered():
    app = Application.builder().token("test").build()
    telegram_bot.build(app)
    assert any("provera" in getattr(handler, "commands", ()) for handler in app.handlers[0])


async def test_startup_check_does_not_block_application_and_is_cleaned_on_shutdown(monkeypatch):
    started = asyncio.Event()

    async def work(bot):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(main.db, "connect", AsyncMock())
    monkeypatch.setattr(main.budget, "configure", Mock())
    monkeypatch.setattr(main.scheduler, "start", Mock())
    monkeypatch.setattr(schema, "startup", work)
    app = SimpleNamespace(bot=SimpleNamespace(), bot_data={})
    await main._post_init(app)
    await started.wait()
    task = app.bot_data["schema_check_task"]
    assert not task.done()
    await main._stop_schema_check(app)
    assert task.cancelled() and not app.bot_data
    await main._stop_schema_check(app)


def test_fingerprint_ignores_order_but_preserves_actual_findings():
    first = {
        "nalazi": [{"baza": "Proba", "fale": [{"ime": "A"}, {"ime": "B"}], "nepracene": ["X", "Y"]}]
    }
    second = {
        "nalazi": [{"nepracene": ["Y", "X"], "fale": [{"ime": "B"}, {"ime": "A"}], "baza": "Proba"}]
    }
    assert schema.fingerprint(first) == schema.fingerprint(second)
    second["nalazi"][0]["fale"].pop()
    assert schema.fingerprint(first) != schema.fingerprint(second)


async def test_auxiliary_check_failure_does_not_escape_startup(monkeypatch):
    monkeypatch.setattr(schema, "expected", lambda: [object()])
    monkeypatch.setattr(schema.db, "pool", Mock(side_effect=RuntimeError("TAJNA")))
    assert await schema.startup(SimpleNamespace()) is None

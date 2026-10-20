"""Stvarne putanje baza se čitaju kroz SDK; ne premeštaju se redovi niti menjaju podešavanja."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest

from dexter import telegram_bot
from dexter.config import settings
from dexter.services import notion_task_map as mapping
from dexter.services import notion_work

BASE = "https://api.notion.com/v1"


def uid(number):
    return str(UUID(int=number))


@pytest.fixture
def workspace(monkeypatch, respx_mock):
    cfg = settings()
    monkeypatch.setattr(cfg, "notion_api_key", "SECRET-NOTION-KEY")
    # Pogrešan Work ID namerno pokazuje na Life da reprodukuje korisnikov problem.
    monkeypatch.setattr(cfg, "notion_tasks_db_id", uid(11))
    monkeypatch.setattr(cfg, "notion_todo_db_id", uid(11))
    dbs, sources, pages = {}, {}, {}

    def title(value):
        return [{"plain_text": value}]

    for number, name, parent in ((1, "Dashboard", None), (2, "Work", 1), (3, "Life", 1)):
        pages[uid(number)] = {
            "object": "page",
            "id": uid(number),
            "properties": {"title": {"type": "title", "title": title(name)}},
            "parent": {"type": "page_id", "page_id": uid(parent)}
            if parent
            else {"type": "workspace", "workspace": True},
        }
    for number, source, parent, field in ((11, 21, 3, "Zadatak"), (12, 22, 2, "Name")):
        dbs[uid(number)] = {
            "object": "database",
            "id": uid(number),
            "title": title("To-do lista"),
            "parent": {"type": "page_id", "page_id": uid(parent)},
            "data_sources": [{"id": uid(source)}],
        }
        sources[uid(source)] = {
            "object": "data_source",
            "id": uid(source),
            "title": title("To-do lista"),
            "parent": {"type": "database_id", "database_id": uid(number)},
            "properties": {
                field: {"type": "title"},
                "Status": {"type": "status"},
                "Rok": {"type": "date"},
            },
        }
    for kind, values in (("pages", pages), ("databases", dbs), ("data_sources", sources)):
        respx_mock.get(url__regex=BASE + f"/{kind}/[^/]+$").mock(
            side_effect=lambda req, values=values: httpx.Response(
                values[req.url.path.split("/")[-1]].get("status", 200),
                json=values[req.url.path.split("/")[-1]],
            )
        )

    def search(request):
        payload = json.loads(request.content)
        assert payload["filter"] == {"property": "object", "value": "data_source"}
        second = payload.get("start_cursor") == "next"
        return httpx.Response(
            200,
            json={
                "results": [sources[uid(22 if second else 21)]],
                "has_more": not second,
                "next_cursor": None if second else "next",
            },
        )

    route = respx_mock.post(f"{BASE}/search").mock(side_effect=search)
    return SimpleNamespace(dbs=dbs, sources=sources, pages=pages, search=route)


async def test_map_exposes_wrong_config_and_distinguishes_same_named_lists(workspace, respx_mock):
    result = await mapping.inspect()
    work, life = result["podeseno"]
    assert work["oblast"] == life["oblast"] == "Life"
    assert work["putanja"] == "Dashboard → Life → To-do lista"
    candidates = {item["oblast"]: item for item in result["dostupne_liste"]}
    assert candidates["Work"]["id"] == uid(12)
    assert candidates["Work"]["putanja"] == "Dashboard → Work → To-do lista"
    assert candidates["Life"]["izvori"][0]["kolone"]["Zadatak"] == "title"
    assert candidates["Work"]["izvori"][0]["kolone"]["Rok"] == "date"
    assert not result["nepotpun_pregled"]
    assert workspace.search.call_count == 2
    # Jedini POST je Notion-ova pretraga; nijedan zahtev ne upisuje podatke.
    assert all(
        call.request.method == "GET" or call.request.url.path == "/v1/search"
        for call in respx_mock.calls
    )
    text = mapping.format_report(result)
    assert "pripada drugoj oblasti" in text and uid(12) in text
    assert "SECRET-NOTION-KEY" not in text


async def test_unavailable_ancestor_is_reported_without_invented_work_path(workspace, respx_mock):
    workspace.pages[uid(2)] = {
        "object": "error",
        "status": 404,
        "code": "object_not_found",
        "message": "SECRET-NOTION-KEY",
    }
    result = await mapping.inspect()
    candidate = next(item for item in result["dostupne_liste"] if item["id"] == uid(12))
    assert candidate["oblast"] == "nije potvrđeno"
    assert "deo putanje nije dostupan" in candidate["putanja"]
    assert "SECRET-NOTION-KEY" not in mapping.format_report(result)


async def test_mapping_cycle_and_search_failure_preserve_configured_results(workspace, respx_mock):
    workspace.pages[uid(3)]["parent"] = {"type": "page_id", "page_id": uid(3)}
    workspace.search.respond(
        400,
        json={
            "object": "error",
            "status": 400,
            "code": "validation_error",
            "message": "SECRET-NOTION-KEY",
        },
    )
    result = await mapping.inspect()
    assert result["nepotpun_pregled"] and result["greske"] == ["APIResponseError"]
    assert result["podeseno"][0]["id"] == uid(11)
    assert "delimičan" in mapping.format_report(result)
    assert "SECRET-NOTION-KEY" not in mapping.format_report(result)


async def test_inventory_limit_is_explicit(workspace, monkeypatch):
    monkeypatch.setattr(mapping, "MAX_SOURCES", 1)
    result = await mapping.inspect()
    assert result["nepotpun_pregled"] and workspace.search.call_count == 1
    assert "najviše 1 izvora" in mapping.format_report(result)


async def test_contract_destination_requires_actual_work_path_and_due_schema(
    workspace, monkeypatch
):
    cfg = settings()
    with pytest.raises(ValueError, match="isti ID"):
        await notion_work.contract_destination()
    monkeypatch.setattr(cfg, "notion_todo_db_id", None)
    with pytest.raises(ValueError, match="nije potvrđena pod Work"):
        await notion_work.contract_destination()
    monkeypatch.setattr(cfg, "notion_tasks_db_id", uid(12))
    destination = await notion_work.contract_destination()
    assert destination == {
        "baza_id": uid(12),
        "izvor_id": uid(22),
        "putanja": "Dashboard → Work → To-do lista",
    }
    workspace.sources[uid(22)]["properties"].pop("Rok")
    with pytest.raises(ValueError, match="Rok"):
        await notion_work.contract_destination()


async def test_contract_destination_does_not_guess_when_parent_unavailable(workspace, monkeypatch):
    monkeypatch.setattr(settings(), "notion_tasks_db_id", uid(12))
    workspace.pages[uid(2)] = {
        "object": "error",
        "status": 404,
        "code": "object_not_found",
        "message": "nema pristupa",
    }
    with pytest.raises(ValueError, match="nije potvrđena pod Work"):
        await notion_work.contract_destination()


async def test_missing_key_makes_no_requests(monkeypatch, respx_mock):
    monkeypatch.setattr(settings(), "notion_api_key", None)
    assert "NOTION_API_KEY" in mapping.format_report(await mapping.inspect())
    assert not respx_mock.calls


async def test_list_command_is_owner_only_and_keeps_default_schema_command(monkeypatch):
    inspect = AsyncMock(return_value={"greska": "Проба"})
    check = AsyncMock(return_value={"provereno": 0})
    monkeypatch.setattr(mapping, "inspect", inspect)
    monkeypatch.setattr(telegram_bot.schema, "check", check)
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=999), message=SimpleNamespace(reply_text=AsyncMock())
    )
    ctx = SimpleNamespace(args=["liste"])
    await telegram_bot.cmd_schema(update, ctx)
    inspect.assert_not_awaited()
    update.effective_chat.id = settings().telegram_owner_chat_id
    await telegram_bot.cmd_schema(update, ctx)
    update.message.reply_text.assert_awaited_once_with("Proba")
    inspect.assert_awaited_once()
    check.assert_not_awaited()
    ctx.args = ["pogresno"]
    await telegram_bot.cmd_schema(update, ctx)
    assert "Upotreba" in update.message.reply_text.call_args.args[0]
    assert inspect.await_count == 1
    ctx.args = []
    await telegram_bot.cmd_schema(update, ctx)
    check.assert_awaited_once()

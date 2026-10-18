import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from dexter.config import settings
from dexter.services import notion_clients as clients
from dexter.services import notion_work as work
from dexter.tools import registry
from dexter.tools.notion_business import (
    ClientAddArgs,
    ClientFindArgs,
    ClientListArgs,
    ClientUpdateArgs,
    KnowledgeArgs,
    TaskAddArgs,
    TaskListArgs,
    TaskStatusArgs,
)


@pytest.fixture
def workspace(monkeypatch, respx_mock):
    base = "https://api.notion.com/v1"
    client_db, client_source, task_db, task_source, kb = [str(uuid4()) for _ in range(5)]
    cfg = settings()
    for name, value in {
        "notion_api_key": "test-notion",
        "notion_clients_db_id": client_db,
        "notion_tasks_db_id": task_db,
        "notion_kb_page_id": kb,
    }.items():
        monkeypatch.setattr(cfg, name, value)
    for database, source in ((client_db, client_source), (task_db, task_source)):
        respx_mock.get(f"{base}/databases/{database}").respond(
            200, json={"data_sources": [{"id": source}]}
        )
    pages = {}

    def page(title="ABC Studio", source=None, **props):
        source = source or client_source
        result = {
            "id": str(uuid4()),
            "url": "https://notion.so/test",
            "parent": {"type": "data_source_id", "data_source_id": source},
            "properties": {
                "Klijent" if source == client_source else "Name": {
                    "type": "title",
                    "title": [{"plain_text": title}],
                },
                **props,
            },
        }
        pages[result["id"]] = result
        return result

    def query(request):
        source = request.url.path.split("/")[-2]
        body = json.loads(request.content)
        result = [p for p in pages.values() if p["parent"].get("data_source_id") == source]
        filter_ = body.get("filter")
        if filter_:
            column = filter_["property"]
            kind = "select" if column == "Aktivan" else "status"
            result = [
                p
                for p in result
                if (p["properties"].get(column, {}).get(kind) or {}).get("name")
                == filter_[kind]["equals"]
            ]
        return httpx.Response(200, json={"results": result[: body["page_size"]], "has_more": False})

    client_query = respx_mock.post(f"{base}/data_sources/{client_source}/query").mock(
        side_effect=query
    )
    task_query = respx_mock.post(f"{base}/data_sources/{task_source}/query").mock(side_effect=query)

    def create(request):
        body = json.loads(request.content)
        result = {"id": str(uuid4()), "url": "https://notion.so/new", **body}
        pages[result["id"]] = result
        return httpx.Response(200, json=result)

    def update(request):
        result = pages[request.url.path.split("/")[-1]]
        result["properties"].update(json.loads(request.content)["properties"])
        return httpx.Response(200, json=result)

    create_route = respx_mock.post(f"{base}/pages").mock(side_effect=create)
    update_route = respx_mock.patch(url__regex=base + r"/pages/[^/]+$").mock(side_effect=update)
    respx_mock.get(url__regex=base + r"/pages/[^/]+$").mock(
        side_effect=lambda request: httpx.Response(200, json=pages[request.url.path.split("/")[-1]])
    )
    append_route = respx_mock.patch(url__regex=base + r"/blocks/[^/]+/children$").respond(
        200, json={"results": []}
    )
    return SimpleNamespace(
        base=base,
        client_db=client_db,
        client_source=client_source,
        task_db=task_db,
        task_source=task_source,
        kb=kb,
        pages=pages,
        page=page,
        client_query=client_query,
        task_query=task_query,
        create=create_route,
        update=update_route,
        append=append_route,
    )


@pytest.mark.parametrize(
    "first,second,expected",
    [
        ("Petar Pavlović PR ABC STUDIO", "ABC Studio", True),
        ("ABC Studio", "Studio ABC d.o.o.", True),
        ("Čarobni đak", "Carobni dak", True),
        ("Чаробни ђак", "Carobni dak", True),
        ("Primer DOO", "Primer", True),
        ("Lab", "DGTL Lab", False),
        ("ABC Studio", "ABC Studio Novi Sad", True),
        ("ABC Studio", "ABC StudioX", False),
        ("DOO", "PR", False),
        ("", "", False),
    ],
)
def test_company_normalization(first, second, expected):
    assert clients.same_company(first, second) is expected


async def test_add_new_only_supplied_data_and_client_defaults(workspace):
    n = workspace
    result = await registry.execute(
        "client_add", {"naziv": "Нова фирма", "domen": "primer.rs", "odrzavanjeCena": 0}
    )
    data = json.loads(result.text)
    assert data["klijent"] == "Nova firma" and not data["dopunjen"]
    props = json.loads(n.create.calls[0].request.content)["properties"]
    assert props == {
        "Klijent": {"title": [{"text": {"content": "Nova firma"}}]},
        "Domen": {"url": "https://primer.rs"},
        "Održavanje cena": {"number": 0},
        "Aktivan": {"select": {"name": "Aktivan"}},
        "Tip": {"select": {"name": "Klijent"}},
    }
    assert data["pib"] == data["mb"] == data["adresa"] == ""
    assert data["naziv"] == "Nova firma" and data["nazivZaFakturu"] == ""
    body = json.loads(n.create.calls[0].request.content)
    assert body["parent"] == {"type": "data_source_id", "data_source_id": n.client_source}
    assert n.client_query.calls[0].request.headers["Notion-Version"] == "2025-09-03"


async def test_add_existing_preserves_title_and_copies_legal_name_only_if_empty(workspace):
    n = workspace
    entry = n.page(Telefon={"phone_number": "123"}, Status={"select": {"name": "Plaćeno"}})
    result = await registry.execute(
        "client_add", {"naziv": "Petar Pavlović PR ABC STUDIO", "pib": "001234567"}
    )
    data = json.loads(result.text)
    assert data["id"] == entry["id"] and data["dopunjen"]
    assert (
        data["klijent"] == "ABC Studio" and data["nazivZaFakturu"] == "Petar Pavlović PR ABC STUDIO"
    )
    assert data["pib"] == "001234567" and data["telefon"] == "123" and data["status"] == "Plaćeno"
    props = json.loads(n.update.calls[0].request.content)["properties"]
    assert set(props) == {"PIB", "Naziv za fakturu"} and not n.create.called
    result = await registry.execute(
        "client_add", {"naziv": "Petar Pavlović PR ABC STUDIO", "email": "kontakt@example.com"}
    )
    assert not result.is_error
    assert set(json.loads(n.update.calls[-1].request.content)["properties"]) == {"Email"}


async def test_add_existing_without_changes_is_noop(workspace):
    workspace.page()
    result = await registry.execute("client_add", {"naziv": "ABC Studio"})
    data = json.loads(result.text)
    assert not data["dopunjen"] and "već postoji" in data["poruka"]
    assert not workspace.create.called and not workspace.update.called


async def test_exact_name_beats_longer_candidate_and_legal_alias(workspace):
    n = workspace
    exact = n.page("Slikaj i Cirkaj")
    n.page("Paketi Slikaj i Cirkaj")
    found = await clients.find("Slikaj i Cirkaj")
    assert [p["id"] for p in found] == [exact["id"]]
    await clients.add({"naziv": "Slikaj i Cirkaj", "opis": "Samo tačan klijent"})
    assert len(n.pages) == 2
    assert n.update.calls[0].request.url.path.endswith(exact["id"])


async def test_ambiguous_client_never_written_and_missing_update_never_created(workspace):
    n = workspace
    n.page("Petar PR ABC Studio")
    n.page("Marko PR ABC Studio")
    for tool_name, args in [
        ("client_add", {"naziv": "ABC Studio", "opis": "proba"}),
        ("client_update", {"klijent": "ABC", "opis": "proba"}),
        ("client_update", {"klijent": "Nema ga", "opis": "proba"}),
    ]:
        assert (await registry.execute(tool_name, args)).is_error
    assert not n.create.called and not n.update.called


async def test_update_maps_all_columns_preserves_omitted_and_handles_zero(workspace):
    n = workspace
    n.page(Telefon={"phone_number": "123"})
    args = {
        "klijent": "ABC",
        "naziv": "ABC Studio novi",
        "nazivZaFakturu": "ABC Studio DOO",
        "domen": "https://primer.rs/putanja",
        "email": "abc@example.com",
        "pib": "001234567",
        "mb": "00123456",
        "adresa": "Primer 1",
        "grad": "Grad",
        "opis": "Напомена",
        "aktivan": "Arhiva",
        "tip": "Interni",
        "status": "Ne plaća",
        "faktura": "Ne plaća",
        "ponuda": "Nije poslato",
        "trajanje": "Nema održavanja",
        "odrzavanjeCena": 0,
        "elementor": "Ne",
        "mojHosting": "Da",
    }
    result = await registry.execute("client_update", args)
    data = json.loads(result.text)
    assert data["opis"] == "Napomena" and data["telefon"] == "123"
    props = json.loads(n.update.calls[0].request.content)["properties"]
    assert set(props) == {
        "Klijent",
        "Naziv za fakturu",
        "Domen",
        "Email",
        "PIB",
        "MB",
        "Adresa",
        "Grad",
        "Opis",
        "Aktivan",
        "Tip",
        "Status",
        "Faktura",
        "Ponuda",
        "Trajanje",
        "Održavanje cena",
        "Elementor",
        "Moj hosting",
    }
    assert props["Održavanje cena"]["number"] == 0 and data["ponuda"] == "Nije poslato"
    assert not n.create.called


async def test_client_empty_fields_do_not_clear_existing(workspace):
    n = workspace
    n.page(PIB={"rich_text": [{"plain_text": "001234567"}]})
    result = await registry.execute(
        "client_update", {"klijent": "ABC", "pib": " ", "opis": "Dopuna"}
    )
    assert json.loads(result.text)["pib"] == "001234567"
    assert set(json.loads(n.update.calls[0].request.content)["properties"]) == {"Opis"}
    assert (await registry.execute("client_update", {"klijent": "ABC"})).is_error


async def test_clients_find_and_upsert_read_all_pages_before_deciding(workspace):
    n = workspace
    first, second = n.page("Drugi klijent"), n.page("ABC Studio")
    responses = [
        httpx.Response(200, json={"results": [first], "has_more": True, "next_cursor": "druga"}),
        httpx.Response(200, json={"results": [second], "has_more": False}),
    ]
    n.client_query.mock(side_effect=responses)
    found = await clients.find("ABC")
    assert len(found) == 1 and found[0]["id"] == second["id"]
    assert json.loads(n.client_query.calls[1].request.content)["start_cursor"] == "druga"
    n.client_query.mock(side_effect=responses)
    assert (await clients.add({"naziv": "ABC Studio", "opis": "Dopuna"}))["dopunjen"]
    assert not n.create.called


async def test_client_list_filter_limit_and_noop_read(workspace):
    n = workspace
    n.page("Aktivni", Aktivan={"select": {"name": "Aktivan"}})
    n.page("Arhiva", Aktivan={"select": {"name": "Arhiva"}})
    result = await registry.execute("client_list", {"aktivan": "Arhiva", "limit": 1})
    assert json.loads(result.text)[0]["klijent"] == "Arhiva"
    body = json.loads(n.client_query.calls[0].request.content)
    assert body == {
        "page_size": 1,
        "filter": {"property": "Aktivan", "select": {"equals": "Arhiva"}},
    }
    assert not n.update.called and not n.create.called


async def test_parallel_client_add_does_not_create_two_rows(workspace):
    n = workspace
    result = await asyncio.gather(
        clients.add({"naziv": "ABC Studio"}), clients.add({"naziv": "Petar PR ABC Studio"})
    )
    assert len(n.pages) == n.create.call_count == 1
    assert sum(p["dopunjen"] for p in result) == 1


async def test_business_tasks_keep_all_statuses_and_filter_only_when_requested(workspace):
    n = workspace
    n.page("Отворен", n.task_source, Status={"status": {"name": "Not started"}})
    n.page("Gotov", n.task_source, Status={"status": {"name": "Done"}})
    result = await registry.execute("notion_list_tasks", {})
    assert [p["title"] for p in json.loads(result.text)] == ["Otvoren", "Gotov"]
    assert "filter" not in json.loads(n.task_query.calls[0].request.content)
    result = await registry.execute("notion_list_tasks", {"status": "Done"})
    assert len(json.loads(result.text)) == 1
    assert json.loads(n.task_query.calls[1].request.content)["filter"] == {
        "property": "Status",
        "status": {"equals": "Done"},
    }


@pytest.mark.parametrize("status", ["Not started", "In progress", "Done"])
async def test_add_business_task_uses_exact_columns(workspace, status):
    n = workspace
    args = {"title": "Пословни задатак"}
    if status != "Not started":
        args["status"] = status
    result = await registry.execute("notion_add_task", args)
    assert not result.is_error and result.pending is None
    assert json.loads(result.text)["title"] == "Poslovni zadatak"
    body = json.loads(n.create.calls[0].request.content)
    assert body["parent"]["data_source_id"] == n.task_source
    assert body["properties"] == {
        "Name": {"title": [{"text": {"content": "Poslovni zadatak"}}]},
        "Status": {"status": {"name": status}},
    }


async def test_task_status_only_changes_status(workspace):
    n = workspace
    entry = n.page("Posao", n.task_source, Status={"status": {"name": "Not started"}})
    result = await registry.execute(
        "notion_update_task_status", {"taskId": entry["id"], "status": "Done"}
    )
    assert json.loads(result.text) == {"id": entry["id"], "url": entry["url"], "status": "Done"}
    assert json.loads(n.update.calls[0].request.content) == {
        "properties": {"Status": {"status": {"name": "Done"}}}
    }


@pytest.mark.parametrize("case", ["wrong_board", "archived", "trash"])
async def test_task_status_refuses_other_board_and_inactive_pages(workspace, case):
    n = workspace
    entry = n.page("Posao", n.task_source)
    if case == "wrong_board":
        entry["parent"]["data_source_id"] = n.client_source
    else:
        entry["archived" if case == "archived" else "in_trash"] = True
    result = await registry.execute(
        "notion_update_task_status", {"taskId": entry["id"], "status": "Done"}
    )
    assert result.is_error and not n.update.called


async def test_query_paginates_limits_active_pages_and_rejects_repeated_cursor(workspace):
    n = workspace
    first, second = n.page(source=n.task_source), n.page(source=n.task_source)
    archived = {**first, "archived": True}
    n.task_query.mock(
        side_effect=[
            httpx.Response(
                200, json={"results": [archived], "has_more": True, "next_cursor": "jos"}
            ),
            httpx.Response(200, json={"results": [second], "has_more": False}),
        ]
    )
    assert len(await work.list_tasks(limit=1)) == 1
    assert json.loads(n.task_query.calls[1].request.content)["page_size"] == 1
    n.task_query.mock(
        return_value=httpx.Response(
            200, json={"results": [], "has_more": True, "next_cursor": "ponovljen"}
        )
    )
    with pytest.raises(ValueError, match="paginaciju"):
        await work.list_tasks()


@pytest.mark.parametrize("content", ["", "Први пасус\n\nDrugi pasus", "Ž" * 5001])
async def test_knowledge_create_page_parent_and_long_rich_text(workspace, content):
    n = workspace
    result = await registry.execute(
        "notion_add_knowledge", {"title": "Белешка", "content": content}
    )
    assert not result.is_error and json.loads(result.text)["title"] == "Beleška"
    body = json.loads(n.create.calls[0].request.content)
    assert body["parent"] == {"type": "page_id", "page_id": n.kb}
    assert body["properties"] == {"title": {"title": [{"text": {"content": "Beleška"}}]}}
    text = [
        "".join(r["text"]["content"] for r in b["paragraph"]["rich_text"]) for b in body["children"]
    ]
    if not content:
        assert text == []
    elif content.startswith("Први"):
        assert text == ["Prvi pasus", "Drugi pasus"]
    else:
        assert text == [content]
        assert all(
            len(r["text"]["content"]) <= 2000 for r in body["children"][0]["paragraph"]["rich_text"]
        )


async def test_knowledge_appends_over_100_paragraphs_without_truncation(workspace):
    n = workspace
    content = "\n".join(f"Pasus {i}" for i in range(205))
    result = await work.add_knowledge("Proba", content)
    assert "status" not in result and n.append.call_count == 2
    blocks = json.loads(n.create.calls[0].request.content)["children"]
    for call in n.append.calls:
        assert call.request.url.path.endswith(f"/{result['id']}/children")
        blocks.extend(json.loads(call.request.content)["children"])
    assert len(blocks) == 205
    assert blocks[-1]["paragraph"]["rich_text"][0]["text"]["content"] == "Pasus 204"


async def test_knowledge_partial_error_keeps_page_link_and_never_repeats_append(workspace):
    n = workspace
    n.append.respond(
        503,
        json={"object": "error", "code": "service_unavailable", "message": "Upis nije potvrđen"},
    )
    result = await registry.execute(
        "notion_add_knowledge", {"title": "Proba", "content": "red\n" * 201}
    )
    data = json.loads(result.text)
    assert data["status"] == "delimicno" and data["potvrdjenoPasusa"] == 100
    assert data["ukupnoPasusa"] == 201 and data["url"] and "ne ponavljaj" in data["napomena"]
    assert n.create.call_count == n.append.call_count == 1


async def test_knowledge_too_many_paragraphs_rejected_before_create(workspace):
    with pytest.raises(ValueError, match="1000"):
        await work.add_knowledge("Proba", "red\n" * 1001)
    assert not workspace.create.called


async def test_transliteration_expansion_keeps_all_client_text(workspace):
    n = workspace
    result = await registry.execute("client_add", {"naziv": "ABC", "opis": "њ" * 2000})
    assert not result.is_error and json.loads(result.text)["opis"] == "nj" * 2000
    spans = json.loads(n.create.calls[0].request.content)["properties"]["Opis"]["rich_text"]
    assert len(spans) == 2 and all(len(span["text"]["content"]) == 2000 for span in spans)


@pytest.mark.parametrize(
    "name,args,database_kind",
    [
        ("client_add", {"naziv": "ABC Studio"}, "client"),
        ("client_update", {"klijent": "ABC", "opis": "Dopuna"}, "client"),
        ("client_find", {"query": "ABC"}, "client"),
        ("client_list", {}, "client"),
        ("notion_add_task", {"title": "Proba"}, "task"),
        ("notion_list_tasks", {}, "task"),
        ("notion_update_task_status", {"taskId": str(uuid4()), "status": "Done"}, "task"),
        ("notion_add_knowledge", {"title": "Proba"}, "kb"),
    ],
)
async def test_every_tool_handles_permission_error(
    workspace, respx_mock, name, args, database_kind
):
    n = workspace
    route = (
        respx_mock.post(f"{n.base}/pages")
        if database_kind == "kb"
        else respx_mock.get(
            f"{n.base}/databases/{n.client_db if database_kind == 'client' else n.task_db}"
        )
    )
    route.respond(
        403, json={"object": "error", "code": "restricted_resource", "message": "Nema pristupa"}
    )
    result = await registry.execute(name, args)
    assert result.is_error and "Nema pristupa" in result.text


async def test_multi_source_database_refused_before_client_write(workspace, respx_mock):
    n = workspace
    respx_mock.get(f"{n.base}/databases/{n.client_db}").respond(
        200, json={"data_sources": [{"id": n.client_source}, {"id": n.task_source}]}
    )
    result = await registry.execute("client_add", {"naziv": "ABC"})
    assert result.is_error and "tačno jedan" in result.text and not n.create.called


@pytest.mark.parametrize(
    "model,args",
    [
        (ClientAddArgs, {"naziv": " "}),
        (ClientFindArgs, {"query": " "}),
        (ClientAddArgs, {"naziv": "ABC", "aktivan": "aktivan"}),
        (ClientAddArgs, {"naziv": "ABC", "odrzavanjeCena": float("nan")}),
        (ClientAddArgs, {"naziv": "ABC", "odrzavanjeCena": -1}),
        (ClientAddArgs, {"naziv": "ABC", "odrzavanjeCena": True}),
        (ClientAddArgs, {"naziv": "ABC", "pib": 123456789}),
        (ClientUpdateArgs, {"klijent": "ABC", "racun": "izmišljen"}),
        (ClientListArgs, {"limit": 0}),
        (TaskListArgs, {"limit": 101}),
        (TaskAddArgs, {"title": "ABC", "status": "Todo"}),
        (TaskStatusArgs, {"taskId": "abc", "status": "Done"}),
        (KnowledgeArgs, {"title": "ABC", "content": "a" * 100001}),
    ],
)
def test_invalid_arguments(model, args):
    with pytest.raises(ValidationError):
        model(**args)


async def test_bad_domain_and_empty_company_core_never_write(workspace):
    n = workspace
    for args in (
        {"naziv": "ABC", "domen": "ftp://example.com"},
        {"naziv": "DOO"},
        {"naziv": "ABC", "domen": "primer rs"},
    ):
        assert (await registry.execute("client_add", args)).is_error
    assert not n.create.called and not n.update.called


def test_new_tool_requirements_and_instructions(workspace, monkeypatch):
    for names, required, field in [
        (
            ("client_add", "client_update", "client_find", "client_list"),
            clients.REQUIRES,
            "notion_clients_db_id",
        ),
        (
            ("notion_add_task", "notion_list_tasks", "notion_update_task_status"),
            work.TASK_REQUIRES,
            "notion_tasks_db_id",
        ),
        (("notion_add_knowledge",), work.KB_REQUIRES, "notion_kb_page_id"),
    ]:
        for name in names:
            t = registry._TOOLS[name]
            assert t.is_enabled() and not t.confirm and t.requires == tuple(required)
        monkeypatch.setattr(settings(), field, None)
        for name in names:
            assert field.upper() in registry._TOOLS[name].disabled_reason()
    assert "ne izmišljaj" in registry._TOOLS["client_add"].description
    assert "dopunjen" in registry._TOOLS["client_add"].description
    assert "netaknuta" in registry._TOOLS["client_update"].description
    assert "Prvo pozovi" in registry._TOOLS["notion_update_task_status"].description


async def test_missing_database_configuration_is_clear(workspace, monkeypatch):
    monkeypatch.setattr(settings(), "notion_clients_db_id", None)
    with pytest.raises(ValueError, match="NOTION_CLIENTS_DB_ID"):
        await clients.find("ABC")
    monkeypatch.setattr(settings(), "notion_kb_page_id", None)
    with pytest.raises(ValueError, match="NOTION_KB_PAGE_ID"):
        await work.add_knowledge("ABC")

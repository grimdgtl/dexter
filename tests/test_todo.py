import json
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import httpx
import pytest
from pydantic import ValidationError

from dexter import cron, jobs, scheduler
from dexter.config import settings
from dexter.services import todo
from dexter.tools import registry
from dexter.tools.todo import AddArgs, ListArgs, StatusArgs


async def test_list_paginates_filters_and_preserves_null_fields(todo_notion, respx_mock):
    n = todo_notion
    route = respx_mock.post(f"{n.base}/data_sources/{n.source}/query").mock(
        side_effect=[
            httpx.Response(
                200, json={"results": [n.page()], "has_more": True, "next_cursor": "jos"}
            ),
            httpx.Response(200, json={"results": [n.page("Други")], "has_more": False}),
        ]
    )
    result = await registry.execute("todo_list", {"limit": 2})
    assert not result.is_error
    rows = json.loads(result.text)
    assert rows[0]["zadatak"] == "Lični zadatak" and rows[1]["zadatak"] == "Drugi"
    assert rows[0]["oblast"] is None and rows[0]["rok"] is None
    bodies = [json.loads(c.request.content) for c in route.calls]
    assert bodies[0]["filter"] == {"property": "Status", "status": {"does_not_equal": "Done"}}
    assert bodies[1]["start_cursor"] == "jos" and bodies[1]["page_size"] == 1
    assert route.calls[0].request.headers["Notion-Version"] == "2025-09-03"


async def test_list_explicit_done_and_bad_cursor(todo_notion, respx_mock):
    n = todo_notion
    route = respx_mock.post(f"{n.base}/data_sources/{n.source}/query").respond(
        200, json={"results": [], "has_more": True, "next_cursor": "ponovljen"}
    )
    with pytest.raises(RuntimeError, match="paginaciju"):
        await todo.list_tasks("Done")
    assert json.loads(route.calls[0].request.content)["filter"]["status"] == {"equals": "Done"}
    assert route.call_count == 2


@pytest.mark.parametrize("optional", [False, True])
async def test_add_properties_and_no_confirmation(todo_notion, respx_mock, optional):
    n = todo_notion
    route = respx_mock.post(f"{n.base}/pages").respond(200, json=n.page())
    args = {"zadatak": "  Лични задатак  "}
    if optional:
        args.update(oblast="Kuća", prioritet="Visok", rok="2026-10-25")
    result = await registry.execute("todo_add", args)
    assert not result.is_error and result.pending is None
    body = json.loads(route.calls[0].request.content)
    assert body["parent"] == {"type": "data_source_id", "data_source_id": n.source}
    props = body["properties"]
    assert props["Zadatak"]["title"][0]["text"]["content"] == "Lični zadatak"
    assert props["Status"] == {"status": {"name": "Not started"}}
    if optional:
        assert props["Rok"] == {"date": {"start": "2026-10-25"}}
        assert props["Oblast"]["select"]["name"] == "Kuća"
        assert props["Prioritet"]["select"]["name"] == "Visok"
    else:
        assert set(props) == {"Zadatak", "Status"}


async def test_status_only_changes_selected_field(todo_notion, respx_mock):
    n = todo_notion
    respx_mock.get(f"{n.base}/pages/{n.task_id}").respond(200, json=n.page())
    page = n.page()
    page["properties"]["Status"]["status"]["name"] = "Done"
    route = respx_mock.patch(f"{n.base}/pages/{n.task_id}").respond(200, json=page)
    result = await registry.execute("todo_set_status", {"zadatakId": n.task_id, "status": "Done"})
    assert not result.is_error and json.loads(result.text)["status"] == "Done"
    assert json.loads(route.calls[0].request.content) == {
        "properties": {"Status": {"status": {"name": "Done"}}}
    }


@pytest.mark.parametrize("change", ["other_database", "archived"])
async def test_status_cannot_modify_another_board_or_archived_task(todo_notion, respx_mock, change):
    n = todo_notion
    page = n.page()
    if change == "other_database":
        page["parent"]["data_source_id"] = n.database
    else:
        page["archived"] = True
    respx_mock.get(f"{n.base}/pages/{n.task_id}").respond(200, json=page)
    route = respx_mock.patch(f"{n.base}/pages/{n.task_id}")
    with pytest.raises(ValueError):
        await todo.set_status(n.task_id, "Done")
    assert not route.called


@pytest.mark.parametrize(
    "name,args,method,path",
    [
        ("todo_list", {}, "POST", "query"),
        ("todo_add", {"zadatak": "Proba"}, "POST", "pages"),
        ("todo_set_status", {"status": "Done"}, "PATCH", "task"),
    ],
)
async def test_tools_report_permission_errors(todo_notion, respx_mock, name, args, method, path):
    n = todo_notion
    if path == "task":
        args = {**args, "zadatakId": n.task_id}
        respx_mock.get(f"{n.base}/pages/{n.task_id}").respond(200, json=n.page())
    url = {
        "query": f"data_sources/{n.source}/query",
        "pages": "pages",
        "task": f"pages/{n.task_id}",
    }[path]
    respx_mock.route(method=method, url=f"{n.base}/{url}").respond(
        403,
        json={
            "object": "error",
            "status": 403,
            "code": "restricted_resource",
            "message": "Pristup odbijen",
        },
    )
    result = await registry.execute(name, args)
    assert result.is_error and "Pristup odbijen" in result.text


@pytest.mark.parametrize("sources", [[], [{"id": "a"}, {"id": "b"}]])
async def test_ambiguous_database_is_rejected(todo_notion, respx_mock, sources):
    n = todo_notion
    respx_mock.get(f"{n.base}/databases/{n.database}").respond(200, json={"data_sources": sources})
    result = await registry.execute("todo_add", {"zadatak": "Proba"})
    assert result.is_error and "tačno jedan" in result.text


def test_requires_and_input_validation(todo_notion, monkeypatch):
    monkeypatch.setattr(settings(), "notion_todo_db_id", None)
    for name in ("todo_list", "todo_add", "todo_set_status"):
        assert "NOTION_TODO_DB_ID" in registry._TOOLS[name].disabled_reason()
    for args in (
        {"zadatak": " "},
        {"zadatak": "a", "oblast": "Posao"},
        {"zadatak": "a", "prioritet": "Hitno"},
        {"zadatak": "a", "rok": "2026-02-30"},
        {"zadatak": "a", "rok": "2026-10-25T10:00:00"},
    ):
        with pytest.raises(ValidationError):
            AddArgs(**args)
    with pytest.raises(ValidationError):
        StatusArgs(zadatakId="nije-id", status="Done")
    with pytest.raises(ValidationError):
        ListArgs(limit=0)


@pytest.mark.parametrize(
    "expression,weekday",
    [
        ("0 5 * * 1", 0),
        ("0 5 * * 0", 6),
        ("0 5 * * 7", 6),
        ("0 5 * * Monday-Friday", 0),
        ("0 5 * * 5-7", 4),
        ("0 5 * * */2", 1),
    ],
)
def test_unix_weekdays(expression, weekday):
    tz = ZoneInfo("Europe/Belgrade")
    after = datetime(2026, 10, 19, tzinfo=tz)
    fire = cron.trigger(expression, str(tz)).get_next_fire_time(None, after)
    assert fire.weekday() == weekday and fire.hour == 5


def test_week_window_crosses_year_and_dst():
    assert todo.week_window(date(2027, 1, 1)) == (date(2026, 12, 28), date(2027, 1, 3))
    assert todo.week_window(date(2026, 10, 25)) == (date(2026, 10, 19), date(2026, 10, 25))


async def test_scheduler_registers_configured_job_and_uses_run_job(todo_notion, monkeypatch):
    monkeypatch.setattr(settings(), "scheduler_enabled", "on")
    monkeypatch.setattr(settings(), "flowers_task_cron", "0 5 * * 1")
    monkeypatch.setattr(scheduler.AsyncIOScheduler, "start", lambda self: None)
    bot = SimpleNamespace(send_message=AsyncMock())
    schedule = scheduler.start(bot)
    job = schedule.get_job("weekly_task")
    assert job is not None
    fire = job.trigger.get_next_fire_time(
        None, datetime(2026, 10, 18, tzinfo=ZoneInfo("Europe/Belgrade"))
    )
    assert fire.isoformat() == "2026-10-19T05:00:00+02:00"
    run = AsyncMock()
    monkeypatch.setattr(jobs, "run_job", run)
    await job.func(*job.args)
    assert run.call_args.args[0] == "weekly_task" and run.call_args.kwargs["bot"] is bot
    monkeypatch.setattr(settings(), "notion_todo_db_id", None)
    assert scheduler.start(bot).get_job("weekly_task") is None


async def test_weekly_notification_only_for_new_task(monkeypatch):
    bot = SimpleNamespace(send_message=AsyncMock())
    create = AsyncMock(
        side_effect=[
            {"zadatak": "Недељни задатак", "rok": "2026-10-25", "vecPostojao": False},
            {"vecPostojao": True},
        ]
    )
    monkeypatch.setattr(todo, "create_weekly", create)
    await scheduler.weekly_task(bot)
    await scheduler.weekly_task(bot)
    bot.send_message.assert_awaited_once()
    assert "Nedeljni zadatak" in bot.send_message.call_args.args[1]

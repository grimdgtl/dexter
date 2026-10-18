import asyncio
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from dexter import llm, usage
from dexter.config import settings
from dexter.services import google, reports
from dexter.tools import registry
from dexter.tools.reports import ReportArgs


@pytest.fixture
def report_setup(monkeypatch):
    for field in (
        "google_client_id",
        "google_client_secret",
        "google_refresh_token",
        "notion_api_key",
        "notion_tasks_db_id",
        "notion_clients_db_id",
    ):
        monkeypatch.setattr(settings(), field, "test")
    monkeypatch.setattr(settings(), "google_calendar_id", "primary")
    monkeypatch.setattr(settings(), "timezone", "Europe/Belgrade")
    monkeypatch.setattr(
        reports, "local_now", lambda: datetime(2026, 10, 18, 12, tzinfo=ZoneInfo("Europe/Belgrade"))
    )
    tasks = AsyncMock(return_value=[{"id": "task", "title": "Proba", "status": "Done"}])
    calendar = AsyncMock(return_value=[{"summary": "Proba događaja"}])
    monitor = AsyncMock(return_value={"checked": 1, "results": [{"ok": True}], "problems": []})
    generated = AsyncMock(
        return_value=SimpleNamespace(
            stop_reason="end_turn", content=[SimpleNamespace(type="text", text="Извештај о проби.")]
        )
    )
    doc = AsyncMock(
        return_value={"id": "report", "name": "Izveštaj", "link": "https://docs.google.com/report"}
    )
    monkeypatch.setattr(reports.notion_work, "list_tasks", tasks)
    monkeypatch.setattr(reports.calendar, "list_events", calendar)
    monkeypatch.setattr(reports.monitor, "check_all_sites", monitor)
    monkeypatch.setattr(reports.llm, "create", generated)
    monkeypatch.setattr(reports.google, "create_doc", doc)
    return SimpleNamespace(
        tasks=tasks, calendar=calendar, monitor=monitor, generated=generated, doc=doc
    )


async def test_report_defaults_real_sources_caveats_and_single_llm_call(report_setup):
    s = report_setup
    result = await reports.generate(ReportArgs(includeSites=True, instructions="Izdvoji rizike"))
    assert result["sacuvano"] and result["content"] == "Izveštaj o probi."
    assert result["doc"]["link"] == "https://docs.google.com/report"
    assert s.tasks.await_count == 3 and s.calendar.await_count == 1 and s.monitor.await_count == 1
    assert s.calendar.call_args.args == ("2026-10-11T12:00:00+02:00", "2026-10-18T12:00:00+02:00")
    s.doc.assert_awaited_once_with("Izveštaj 2026-10-18", "Izveštaj o probi.")
    call = s.generated.call_args.kwargs
    assert call["purpose"] == "report" and call["model"] == settings().model_fast
    assert s.generated.await_count == 1
    assert "PODATAK" in call["system"] and "Done ne znači" in call["system"]
    assert "Izdvoji rizike" in call["messages"][0]["content"]


async def test_report_can_return_text_without_drive_and_excludes_unselected_sources(report_setup):
    s = report_setup
    result = await reports.generate(
        ReportArgs(includeTasks=False, includeSites=False, saveToDoc=False)
    )
    assert not result["sacuvano"] and "doc" not in result
    s.doc.assert_not_awaited()
    s.tasks.assert_not_awaited()
    s.monitor.assert_not_awaited()
    s.calendar.assert_awaited_once()


async def test_report_marks_partial_failure_in_returned_and_saved_text(report_setup):
    s = report_setup
    s.calendar.side_effect = RuntimeError("Privatna tajna")
    result = await reports.generate(ReportArgs())
    assert result["sacuvano"]
    assert "kalendar nije dostupan" in result["content"]
    assert "Privatna tajna" not in str(result) and "Privatna tajna" not in str(
        s.generated.call_args
    )
    assert "kalendar nije dostupan" in s.doc.call_args.args[1]


async def test_report_marks_missing_source_and_task_limit(report_setup, monkeypatch):
    s = report_setup
    s.tasks.return_value = [{"title": f"Zadatak {i}"} for i in range(51)]
    monkeypatch.setattr(settings(), "notion_clients_db_id", None)
    result = await reports.generate(ReportArgs(includeSites=True))
    assert "sajtovi nije podešen" in result["content"]
    raw = json.loads(s.generated.call_args.kwargs["messages"][0]["content"].split("Podaci:\n")[1])
    for group in raw["podaci"]["zadaci"]["statusi"].values():
        assert group["ograniceno"] and len(group["zadaci"]) == 50


@pytest.mark.parametrize("case", ["no_sources", "all_failed", "large", "unfinished", "empty"])
async def test_incomplete_reports_are_not_saved(report_setup, case):
    s = report_setup
    args = ReportArgs()
    if case == "no_sources":
        args = ReportArgs(includeTasks=False, includeCalendar=False)
    elif case == "all_failed":
        s.tasks.side_effect = s.calendar.side_effect = RuntimeError("Nema izvora")
    elif case == "large":
        s.calendar.return_value = [{"summary": "x" * 80001}]
    elif case == "unfinished":
        s.generated.return_value.stop_reason = "max_tokens"
    else:
        s.generated.return_value.content = []
    with pytest.raises(ValueError):
        await reports.generate(args)
    s.doc.assert_not_awaited()
    if case in {"no_sources", "all_failed", "large"}:
        s.generated.assert_not_awaited()


async def test_report_cancel_propagates_without_saving(report_setup):
    report_setup.calendar.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await reports.generate(ReportArgs())
    report_setup.generated.assert_not_awaited()
    report_setup.doc.assert_not_awaited()


@pytest.mark.parametrize(
    "bounds",
    [
        {"from": "2026-10-19", "to": "2026-10-18"},
        {"from": "2026-10-18", "to": "2026-10-18"},
        {"from": "2024-01-01", "to": "2026-10-18"},
        {"from": "2026-02-30"},
        {"from": "juče"},
        {"to": "2026-10-18T12:00:00"},
    ],
)
async def test_report_rejects_bad_dates_before_io(report_setup, bounds):
    with pytest.raises(ValueError):
        await reports.generate(ReportArgs(**bounds))
    report_setup.tasks.assert_not_awaited()
    report_setup.generated.assert_not_awaited()


async def test_uncertain_drive_save_returns_text_and_does_not_retry(report_setup):
    s = report_setup
    s.doc.side_effect = RuntimeError("Izgubljen odgovor")
    result = await reports.generate(ReportArgs())
    assert not result["sacuvano"] and "doc" not in result
    assert "Izveštaj" in result["content"] and "Proveri Drive" in str(result["napomene"])
    assert s.doc.await_count == 1


async def test_reports_require_google(report_setup, monkeypatch):
    monkeypatch.setattr(settings(), "google_refresh_token", None)
    assert "GOOGLE_REFRESH_TOKEN" in registry._TOOLS["generate_report"].disabled_reason()
    assert (await registry.execute("generate_report", {})).is_error


async def test_report_model_failure_does_not_create_doc(report_setup):
    report_setup.generated.side_effect = RuntimeError("Model nije dostupan")
    out = await registry.execute("generate_report", {})
    assert out.is_error
    report_setup.doc.assert_not_awaited()


async def test_report_uses_real_notion_calendar_anthropic_and_drive_transports(
    monkeypatch, respx_mock, anthropic_client
):
    from dexter import budget

    cfg = settings()
    for name in google.REQUIRES:
        monkeypatch.setattr(cfg, name.lower(), "test")
    monkeypatch.setattr(cfg, "notion_api_key", "test")
    monkeypatch.setattr(cfg, "notion_tasks_db_id", "tasks")
    monkeypatch.setattr(cfg, "google_calendar_id", "primary")
    monkeypatch.setattr(llm, "_client", anthropic_client)
    monkeypatch.setattr(budget, "model_for", AsyncMock(return_value=cfg.model_fast))
    recorder = AsyncMock()
    monkeypatch.setattr(usage, "record", recorder)
    respx_mock.get("https://api.notion.com/v1/databases/tasks").respond(
        200, json={"data_sources": [{"id": "source"}]}
    )
    notion_query = respx_mock.post("https://api.notion.com/v1/data_sources/source/query").respond(
        200, json={"results": [], "has_more": False}
    )
    respx_mock.post("https://oauth2.googleapis.com/token").respond(
        200, json={"access_token": "test", "expires_in": 3600, "token_type": "Bearer"}
    )
    calendar = respx_mock.get(
        "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    ).respond(
        200,
        json={
            "items": [
                {
                    "id": "event",
                    "summary": "Проба",
                    "start": {"date": "2026-10-18"},
                    "end": {"date": "2026-10-19"},
                }
            ]
        },
    )
    model = respx_mock.post("https://api.anthropic.com/v1/messages").respond(
        200,
        json={
            "id": "msg-report",
            "type": "message",
            "role": "assistant",
            "model": cfg.model_fast,
            "content": [{"type": "text", "text": "Извештај: један догађај, без задатака."}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 200, "output_tokens": 50},
        },
    )
    upload = respx_mock.post("https://www.googleapis.com/upload/drive/v3/files").respond(
        200, json={"id": "doc", "name": "Proba", "webViewLink": "https://docs.google.com/doc"}
    )
    result = await registry.execute(
        "generate_report", {"title": "Проба", "from": "2026-10-11", "to": "2026-10-19"}
    )
    assert not result.is_error
    data = json.loads(result.text)
    assert data["sacuvano"] and data["doc"]["id"] == "doc" and data["title"] == "Proba"
    assert "Izveštaj: jedan događaj" in data["content"]
    assert (
        notion_query.call_count == 3
        and calendar.call_count == model.call_count == upload.call_count == 1
    )
    assert (
        b"Izve" in upload.calls[0].request.content
        and google.DOC.encode() in upload.calls[0].request.content
    )
    assert recorder.call_args.args[1] == "report"

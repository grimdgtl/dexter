"""Zamrznut v1 ugovor sprečava gubitak alata ili argumenta pri kasnijim izmenama."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from telegram.ext import Application

from dexter import scheduler, telegram_bot
from dexter.config import Settings, settings
from dexter.tools import registry

CONTRACT = json.loads((Path(__file__).with_name("fixtures") / "apu_contract.json").read_text())
TOOLS = CONTRACT["tools"]


def test_all_46_legacy_tools_have_one_registered_replacement():
    assert len(TOOLS) == 46
    old = {tool["v1"] for tool in TOOLS}
    replacements = {tool["dexter"] for tool in TOOLS}
    assert len(old) == len(replacements) == 46
    assert replacements <= registry._TOOLS.keys()
    production = {
        name
        for name, tool in registry._TOOLS.items()
        if tool.fn.__module__.startswith("dexter.tools.")
    }
    assert production - replacements == {
        "commitment_done",
        "commitments_list",
        "contract_get",
        "contract_task_create",
        "memory_search",
        "proactive_log",
        "receipt_extract",
        "web_search",
    }


@pytest.mark.parametrize("contract", TOOLS, ids=lambda tool: tool["v1"])
def test_legacy_arguments_are_preserved_without_new_required_fields(contract):
    actual = registry._TOOLS[contract["dexter"]].schema()["input_schema"]
    assert set(contract["arguments"]) <= actual["properties"].keys()
    assert set(actual.get("required", [])) <= set(contract["required"])


@pytest.mark.parametrize(
    "name",
    [
        "mail_send",
        "invoice_create",
        "memory_forget",
        "calendar_create_event",
        "receipt_extract",
        "contract_task_create",
    ],
)
def test_destructive_or_external_sensitive_actions_keep_confirmation(name):
    tool = registry._TOOLS[name]
    assert tool.confirm
    if name == "invoice_create":
        assert tool.prepare and tool.preview
        assert tool.confirm_label == "💾 Sačuvaj" and tool.cancel_label == "❌ Odbaci"


def test_all_five_legacy_commands_have_handlers():
    app = Application.builder().token("test").build()
    telegram_bot.build(app)
    commands = {
        command for handler in app.handlers[0] for command in getattr(handler, "commands", ())
    }
    assert {"start", "reset", "status", "poslovi", "provera"} <= commands


def test_all_14_legacy_jobs_keep_default_cron_env_and_wrapper(monkeypatch):
    cfg = Settings(
        _env_file=None,
        telegram_bot_token="test",
        telegram_owner_chat_id=1,
        anthropic_api_key="test",
    )
    expected = {
        "knowledge_index": ("semantic_index_cron", "0 4 * * *"),
        "prepare_day": ("checklist_create_cron", "0 5 * * *"),
        "weekly_task": ("flowers_task_cron", "0 5 * * 1"),
        "morning": ("morning_greeting_cron", "0 6 * * *"),
        "morning_briefing": ("morning_briefing_cron", "30 9 * * *"),
        "mail_check": ("mail_check_cron", "0 8-22 * * *"),
        "site_check_silent": ("site_check_silent_cron", "0 10 * * *"),
        "birthday_morning": ("birthday_morning_cron", "0 11 * * *"),
        "site_check_report": ("site_check_report_cron", "0 18 * * *"),
        "birthday_evening": ("birthday_evening_cron", "0 19 * * *"),
        "checklist_reminder": ("checklist_reminder_cron", "30 21 * * *"),
        "checklist_praise": ("checklist_praise_cron", "0 23 * * *"),
        "weekly_summary": ("weekly_summary_cron", "0 22 * * 0"),
        "tax_reminder": ("tax_reminder_cron", "0 10 14 * *"),
    }
    monkeypatch.setattr(settings(), "scheduler_enabled", "on")
    monkeypatch.setattr(scheduler, "available", lambda requirements: True)
    monkeypatch.setattr(scheduler.todo, "available", lambda: True)
    monkeypatch.setattr(scheduler.mail, "configured", lambda: True)
    monkeypatch.setattr(scheduler.sources, "available", lambda: ["razgovor"])
    monkeypatch.setattr(scheduler.AsyncIOScheduler, "start", Mock())
    schedule = scheduler.start(SimpleNamespace())
    assert set(expected) <= {job.id for job in schedule.get_jobs()}
    for job_id, (field, expression) in expected.items():
        assert getattr(cfg, field) == expression
        assert schedule.get_job(job_id).func.__name__ == "safe"


async def test_start_command_ignores_non_owner_and_greets_owner():
    from unittest.mock import AsyncMock

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=999), message=SimpleNamespace(reply_text=AsyncMock())
    )
    await telegram_bot.cmd_start(update, None)
    update.message.reply_text.assert_not_awaited()
    update.effective_chat.id = 1
    await telegram_bot.cmd_start(update, None)
    assert "Zdravo" in update.message.reply_text.call_args.args[0]


@pytest.mark.parametrize("args", [[], ["12"], ["nije-broj"], ["0"], ["8761"]])
async def test_jobs_command_owner_default_and_range_validation(monkeypatch, args):
    from unittest.mock import AsyncMock

    from dexter import jobs

    async def report(hours):
        if not 1 <= hours <= 8760:
            raise ValueError("Opseg")
        return "Poslovi su provereni."

    runner = AsyncMock(side_effect=report)
    monkeypatch.setattr(jobs, "report", runner)
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=999), message=SimpleNamespace(reply_text=AsyncMock())
    )
    context = SimpleNamespace(args=args)
    await telegram_bot.cmd_jobs(update, context)
    runner.assert_not_awaited()
    update.effective_chat.id = 1
    await telegram_bot.cmd_jobs(update, context)
    message = update.message.reply_text.call_args.args[0]
    if args and args[0] not in {"12"}:
        assert "Upotreba: /poslovi" in message
    else:
        runner.assert_awaited_once_with(12 if args else 24)
        assert message == "Poslovi su provereni."

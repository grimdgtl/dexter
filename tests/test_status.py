"""Razlozi isključenja alata i pregled dostupnosti baze."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from pydantic import BaseModel

from apu import status, telegram_bot
from apu.tools import registry


class Args(BaseModel):
    pass


async def test_requirements_gate_schema_and_execution(monkeypatch):
    cfg = SimpleNamespace(notion_api_key=None, notion_tasks_db_id="baza")
    monkeypatch.setattr(registry, "settings", lambda: cfg)
    fn = AsyncMock(return_value="Gotovo.")
    t = registry.Tool(
        "test_uslovi", "Test.", Args, fn, requires=("NOTION_API_KEY", "NOTION_TASKS_DB_ID")
    )
    monkeypatch.setattr(registry, "_TOOLS", {t.name: t})
    assert t.disabled_reason() == "Nedostaje: NOTION_API_KEY"
    assert registry.schemas() == []
    assert (await registry.execute(t.name, {})).is_error
    fn.assert_not_awaited()
    cfg.notion_api_key = "tajna"
    assert t.disabled_reason() is None
    assert registry.schemas()[0]["name"] == t.name
    assert not (await registry.execute(t.name, {})).is_error


async def test_status_handles_unavailable_database(monkeypatch):
    monkeypatch.setattr(
        status,
        "pool",
        lambda: SimpleNamespace(fetchrow=AsyncMock(side_effect=RuntimeError("postgresql://tajna"))),
    )
    text = await status.report()
    assert "Baza: nedostupna" in text and "tajna" not in text
    assert "Modeli:" in text and "Embeddinzi:" in text


async def test_status_command_is_owner_only_and_transliterates(monkeypatch):
    monkeypatch.setattr(status, "report", AsyncMock(return_value="Стање базе"))
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=999), message=message)
    await telegram_bot.cmd_status(update, None)
    status.report.assert_not_awaited()
    update.effective_chat.id = 1
    await telegram_bot.cmd_status(update, None)
    message.reply_text.assert_awaited_once_with("Stanje baze")

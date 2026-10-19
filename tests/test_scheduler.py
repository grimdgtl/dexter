from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from dexter import main, scheduler, status
from dexter.config import settings


async def test_disabled_scheduler_keeps_startup_and_status_available(monkeypatch):
    monkeypatch.setattr(settings(), "scheduler_enabled", "off")
    connect = AsyncMock()
    configure = Mock()
    constructor = Mock(side_effect=AssertionError("Scheduler ne sme da nastane."))
    monkeypatch.setattr(main.db, "connect", connect)
    monkeypatch.setattr(main.budget, "configure", configure)
    monkeypatch.setattr(scheduler, "AsyncIOScheduler", constructor)
    monkeypatch.setattr(main.schema, "startup", AsyncMock())
    app = SimpleNamespace(bot=SimpleNamespace(), bot_data={})

    await main._post_init(app)
    await app.bot_data["schema_check_task"]
    main.schema.startup.assert_awaited_once_with(app.bot)

    connect.assert_awaited_once()
    configure.assert_called_once_with(app.bot)
    constructor.assert_not_called()
    monkeypatch.setattr(
        status,
        "pool",
        lambda: SimpleNamespace(
            fetchrow=AsyncMock(
                return_value={
                    "documents": 0,
                    "chunks": 0,
                    "facts": 0,
                }
            )
        ),
    )
    assert "Automatski poslovi: isključeni" in await status.report()


def test_enabled_scheduler_keeps_automatic_jobs(monkeypatch):
    monkeypatch.setattr(settings(), "scheduler_enabled", "on")
    monkeypatch.setattr(scheduler.AsyncIOScheduler, "start", lambda self: None)
    schedule = scheduler.start(SimpleNamespace())
    assert {"morning", "conversation_summaries", "daily_insight", "weekly_review"} <= {
        job.id for job in schedule.get_jobs()
    }

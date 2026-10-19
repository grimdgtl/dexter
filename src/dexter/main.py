"""Ulazna tačka: baza → alati → Telegram bot → scheduler."""

import asyncio
import logging

from telegram.ext import Application

from dexter import budget, db, scheduler, telegram_bot
from dexter.config import settings
from dexter.services import schema
from dexter.tools import registry


async def _post_init(app: Application) -> None:
    await db.connect()
    budget.configure(app.bot)
    import dexter.tools  # noqa: F401  registruje alate

    names = [t.name for t in registry.enabled_tools()]
    logging.getLogger("dexter").info("Aktivni alati (%d): %s", len(names), ", ".join(names))
    scheduler.start(app.bot)
    app.bot_data["schema_check_task"] = asyncio.create_task(
        schema.startup(app.bot), name="notion-schema-check"
    )


async def _stop_schema_check(app: Application) -> None:
    task = app.bot_data.pop("schema_check_task", None)
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def run() -> None:
    cfg = settings()
    logging.basicConfig(
        level=cfg.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    app = (
        Application.builder()
        .token(cfg.telegram_bot_token)
        .post_init(_post_init)
        .post_stop(_stop_schema_check)
        .post_shutdown(_stop_schema_check)
        .build()
    )
    telegram_bot.build(app)
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    run()

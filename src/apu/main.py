"""Ulazna tačka: baza → alati → Telegram bot → scheduler."""

import logging

from telegram.ext import Application

from apu import budget, db, scheduler, telegram_bot
from apu.config import settings
from apu.tools import registry


async def _post_init(app: Application) -> None:
    await db.connect()
    budget.configure(app.bot)
    import apu.tools  # noqa: F401  registruje alate

    names = [t.name for t in registry.enabled_tools()]
    logging.getLogger("apu").info("Aktivni alati (%d): %s", len(names), ", ".join(names))
    scheduler.start(app.bot)


def run() -> None:
    cfg = settings()
    logging.basicConfig(
        level=cfg.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    app = Application.builder().token(cfg.telegram_bot_token).post_init(_post_init).build()
    telegram_bot.build(app)
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    run()

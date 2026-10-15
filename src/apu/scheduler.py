"""Zakazani poslovi (preneto iz scheduler.js, postepeno).

Za sada samo jutarnji pozdrav kao primer šablona. Ostali poslovi iz stare
verzije (brifing u 9:30, provera mejla, sajtova, checklista, rođendani,
porez…) se prebacuju u fazi 1b, isto ovako: sakupi podatke alatima,
brzi model napiše poruku, pošalji vlasniku.

Faza 6 dodaje PROAKTIVNOST: agent sam, jednom dnevno, pogleda kalendar,
zadatke i memoriju i javi se samo ako ima nešto vredno ("Petak ti je
pretrpan, a rok za Dijagnozu je ponedeljak — da pomerimo nešto?").
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Bot

from apu import jobs, llm
from apu.agent.prompts import SYSTEM_PROMPT
from apu.config import settings
from apu.pismo import u_latinicu
from apu.tools.weather import WeatherArgs, weather_get

log = logging.getLogger(__name__)


async def morning_greeting(bot: Bot) -> None:
    weather = await weather_get(WeatherArgs(dana=1))
    text = await llm.complete(
        "Napiši kratak jutarnji pozdrav (2-4 reda) sa prognozom i jednom toplom, "
        f"nepatetičnom rečenicom za početak dana. Prognoza: {weather}",
        system=SYSTEM_PROMPT,
        purpose="scheduler",
        max_tokens=400,
    )
    await bot.send_message(settings().telegram_owner_chat_id, u_latinicu(text))


def start(bot: Bot) -> AsyncIOScheduler:
    tz = settings().timezone
    sched = AsyncIOScheduler(timezone=tz)

    async def safe(job, *args):
        return await jobs.run_job(job.__name__, lambda: job(*args), bot=bot)

    sched.add_job(safe, CronTrigger.from_crontab("0 6 * * *", timezone=tz),
                  args=[morning_greeting, bot], id="morning")  # fmt: skip
    sched.start()
    log.info("Scheduler pokrenut (%d poslova).", len(sched.get_jobs()))
    return sched

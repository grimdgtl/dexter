"""Svih 14 v1 rasporeda, uz odvojene F2/F6 poslove i jedinstvenu evidenciju izvršavanja."""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Bot

from dexter import commitments, cron, jobs, proactive, sources
from dexter.config import settings
from dexter.scheduled_jobs import (
    available,
    birthday_evening,
    birthday_morning,
    checklist_praise,
    checklist_reminder,
    mail_check,
    morning_briefing,
    morning_greeting,
    prepare_day,
    site_check_report,
    site_check_silent,
    tax_reminder,
    weekly_summary,
    weekly_task,
)
from dexter.services import birthdays, checklist, mail, monitor, todo

log = logging.getLogger(__name__)


async def conversation_summaries() -> dict:
    return await sources.reindex("razgovor")


def start(bot: Bot) -> AsyncIOScheduler | None:
    cfg = settings()
    if cfg.scheduler_enabled == "off":
        log.info("Automatski poslovi su isključeni (SCHEDULER_ENABLED=off).")
        return None
    tz = cfg.timezone
    sched = AsyncIOScheduler(timezone=tz)

    async def safe(job, *args):
        return await jobs.run_job(
            job.__name__,
            lambda: job(*args),
            bot=bot,
            notify_failure=job not in (proactive.daily, proactive.weekly, commitments.remind),
        )

    entries = (
        ("morning", "morning_greeting_cron", morning_greeting, True),
        ("morning_briefing", "morning_briefing_cron", morning_briefing, True),
        ("tax_reminder", "tax_reminder_cron", tax_reminder, True),
        ("knowledge_index", "semantic_index_cron", sources.reindex, bool(sources.available())),
        ("weekly_task", "flowers_task_cron", weekly_task, todo.available()),
        ("prepare_day", "checklist_create_cron", prepare_day, available(checklist.REQUIRES)),
        (
            "checklist_reminder",
            "checklist_reminder_cron",
            checklist_reminder,
            available(checklist.REQUIRES),
        ),
        (
            "checklist_praise",
            "checklist_praise_cron",
            checklist_praise,
            available(checklist.REQUIRES),
        ),
        ("weekly_summary", "weekly_summary_cron", weekly_summary, available(checklist.REQUIRES)),
        ("mail_check", "mail_check_cron", mail_check, mail.configured()),
        (
            "site_check_silent",
            "site_check_silent_cron",
            site_check_silent,
            available(monitor.REQUIRES),
        ),
        (
            "site_check_report",
            "site_check_report_cron",
            site_check_report,
            available(monitor.REQUIRES),
        ),
        (
            "birthday_morning",
            "birthday_morning_cron",
            birthday_morning,
            available(birthdays.REQUIRES),
        ),
        (
            "birthday_evening",
            "birthday_evening_cron",
            birthday_evening,
            available(birthdays.REQUIRES),
        ),
    )
    for job_id, setting, fn, enabled in entries:
        if enabled:
            args = [] if fn in (sources.reindex, prepare_day) else [bot]
            sched.add_job(
                safe,
                cron.trigger(getattr(cfg, setting), tz),
                args=[fn, *args],
                id=job_id,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=300,
            )
    for job_id, expression, fn, args in (
        ("conversation_summaries", "30 3 * * *", conversation_summaries, []),
        ("commitment_reminders", "0 9 * * *", commitments.remind, [bot]),
        ("daily_insight", "30 8 * * *", proactive.daily, [bot]),
    ):
        sched.add_job(
            safe,
            cron.trigger(expression, tz),
            args=[fn, *args],
            id=job_id,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )
    sched.add_job(
        safe,
        CronTrigger(day_of_week="sun", hour=20, minute=0, timezone=tz),
        args=[proactive.weekly, bot],
        id="weekly_review",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    sched.start()
    log.info("Scheduler pokrenut (%d poslova).", len(sched.get_jobs()))
    return sched

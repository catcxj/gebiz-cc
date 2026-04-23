from __future__ import annotations

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ..config import settings
from ..services.sync import run_sync
from ..services.alerts import run_closing_reminders

log = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = AsyncIOScheduler(timezone=settings.scrape_timezone)

    # Scrape on configured cron (default every 4h)
    _scheduler.add_job(
        run_sync,
        CronTrigger.from_crontab(settings.scrape_cron, timezone=settings.scrape_timezone),
        id="scrape", replace_existing=True, coalesce=True, max_instances=1,
    )

    # Closing-soon reminders hourly — cheap, and ensures countdowns fire on time.
    _scheduler.add_job(
        run_closing_reminders,
        CronTrigger.from_crontab("5 * * * *", timezone=settings.scrape_timezone),
        id="closing-reminders", replace_existing=True, coalesce=True, max_instances=1,
    )

    _scheduler.start()
    log.info("scheduler started: scrape cron=%s", settings.scrape_cron)


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None

"""APScheduler-based reminders for morning plan and evening check-in."""
from __future__ import annotations

import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import (
    REMINDER_PLAN_HOUR,
    REMINDER_PLAN_MINUTE,
    REMINDER_RESULTS_HOUR,
    REMINDER_RESULTS_MINUTE,
    TIMEZONE,
)
from db.base import get_session_factory
from db.repos import get_all_telegram_ids

logger = logging.getLogger(__name__)


async def _send_to_all(bot: Bot, text: str) -> None:
    """Send a message to all registered users."""
    try:
        async with get_session_factory()() as session:
            ids = await get_all_telegram_ids(session)
        for tid in ids:
            try:
                await bot.send_message(chat_id=tid, text=text)
            except Exception as e:
                logger.warning("Reminder to %s failed: %s", tid, e)
    except Exception as e:
        logger.exception("Reminder broadcast failed: %s", e)


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Create and start the scheduler with morning/evening reminders."""
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    scheduler.add_job(
        _send_to_all,
        trigger="cron",
        hour=REMINDER_PLAN_HOUR,
        minute=REMINDER_PLAN_MINUTE,
        args=[bot, "☀️ Доброе утро! Пора составить план на день: /plan"],
        id="morning_plan",
        replace_existing=True,
    )

    scheduler.add_job(
        _send_to_all,
        trigger="cron",
        hour=REMINDER_RESULTS_HOUR,
        minute=REMINDER_RESULTS_MINUTE,
        args=[bot, "🌙 Время подвести итоги дня: /checkin"],
        id="evening_checkin",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "Scheduler started: plan@%02d:%02d, checkin@%02d:%02d (%s)",
        REMINDER_PLAN_HOUR, REMINDER_PLAN_MINUTE,
        REMINDER_RESULTS_HOUR, REMINDER_RESULTS_MINUTE,
        TIMEZONE,
    )
    return scheduler


def shutdown_scheduler(scheduler: AsyncIOScheduler) -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

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
from app.services.mcp_client import MCPMotivationClient
from db.base import get_session_factory
from db.repos import get_all_telegram_ids

logger = logging.getLogger(__name__)

_MOTIVATION_SYSTEM = """\
You are a concise personal coach (12 Week Year methodology).
Generate a short motivation message in Russian (2-4 sentences, 1-2 emoji max).
Do not start with greetings. Reference specific data.
End with a tiny call-to-action.
"""


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


def _build_motivation_user_prompt(ctx: dict) -> str:
    """Build user prompt for motivation generation from MCP context."""
    engagement = (ctx.get("engagement") or {}) if isinstance(ctx, dict) else {}
    achievements = (ctx.get("achievements") or {}) if isinstance(ctx, dict) else {}

    level = engagement.get("engagement_level", "unknown")
    hours = engagement.get("hours_inactive")
    streak = achievements.get("current_streak", 0)
    consistency = achievements.get("consistency", 0)
    trend = achievements.get("trend", "stable")
    week_activities = achievements.get("total_activities", 0)
    breakdown = achievements.get("breakdown", {})

    msg_type = ctx.get("recommended_type", "support")
    tone = ctx.get("recommended_tone", "encouraging")
    style = ctx.get("style", engagement.get("style", "balanced"))

    try:
        consistency_pct = int(round(float(consistency) * 100))
    except (TypeError, ValueError):
        consistency_pct = 0
    inactive_hours = "n/a" if hours is None else str(hours)

    lines = [
        f"Engagement: {level}, inactive {inactive_hours}h",
        f"Streak: {streak}d, consistency: {consistency_pct}%, trend: {trend}",
        f"Week activities: {week_activities}, breakdown: {breakdown}",
        f"Message type: {msg_type}, tone: {tone}, style: {style}",
    ]

    recent = ctx.get("recent_motivations", [])
    if isinstance(recent, list):
        messages: list[str] = []
        for item in recent[:3]:
            if isinstance(item, dict):
                text = str(item.get("message", "")).replace("\n", " ").strip()
                if text:
                    messages.append(text[:60])
        if messages:
            lines.append(f"Recent motivations (don't repeat): {' | '.join(messages)}")

    return "\n".join(lines)


async def check_and_send_motivation(
    bot: Bot,
    mcp_client: MCPMotivationClient,
    openai_service,
    user_repo=None,
) -> None:
    """Check engagement and send motivation messages to eligible users."""
    logger.info("Motivation check started")
    try:
        users = await mcp_client.get_users_needing_motivation()
    except Exception as exc:
        logger.exception("Failed to fetch users needing motivation: %s", exc)
        return

    if not users:
        logger.info("No users need motivation right now")
        return

    for uid in users:
        try:
            ctx = await mcp_client.generate_motivation_context(uid)
            if not isinstance(ctx, dict) or "error" in ctx:
                continue

            user_prompt = _build_motivation_user_prompt(ctx)
            extra = ""

            if user_repo is not None:
                try:
                    vision = None
                    if hasattr(user_repo, "get_vision_text"):
                        vision = await user_repo.get_vision_text(uid)
                    elif hasattr(user_repo, "get_user_vision"):
                        vision = await user_repo.get_user_vision(uid)
                    elif hasattr(user_repo, "get_vision_by_telegram_id"):
                        vision = await user_repo.get_vision_by_telegram_id(uid)
                    if vision:
                        extra = f"\nUser vision: {str(vision)[:200]}"
                except Exception:
                    pass

            ai_message = await openai_service.chat(
                system=_MOTIVATION_SYSTEM,
                user=user_prompt + extra,
                max_tokens=300,
            )
            ai_message = (ai_message or "").strip()
            if not ai_message:
                continue

            await bot.send_message(uid, ai_message, parse_mode="HTML")

            engagement = ctx.get("engagement", {}) if isinstance(ctx.get("engagement"), dict) else {}
            await mcp_client.record_motivation_sent(
                user_id=uid,
                message_type=str(ctx.get("recommended_type", "support")),
                engagement_level=str(engagement.get("engagement_level", "")),
                message=ai_message,
            )
            logger.info("Motivation message sent to user %s", uid)
        except Exception as exc:
            logger.exception("Failed to process motivation for user %s: %s", uid, exc)
            continue


def register_motivation_job(
    scheduler: AsyncIOScheduler,
    bot: Bot,
    mcp_client: MCPMotivationClient,
    openai_service,
    user_repo=None,
) -> None:
    """Register periodic motivation check job in APScheduler."""
    scheduler.add_job(
        check_and_send_motivation,
        "interval",
        minutes=15,
        kwargs={
            "bot": bot,
            "mcp_client": mcp_client,
            "openai_service": openai_service,
            "user_repo": user_repo,
        },
        id="motivation_check",
        replace_existing=True,
        misfire_grace_time=120,
    )

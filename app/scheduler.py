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
You are a clinical psychologist, psychotherapist, and personal coach.
You combine the 12 Week Year methodology with evidence-based therapeutic approaches.

## YOUR THERAPEUTIC FRAMEWORK

Use ONLY scientifically grounded methods:
- CBT (cognitive-behavioral therapy): identify and reframe cognitive distortions
- ACT (acceptance and commitment therapy): values-driven action despite discomfort
- Behavioral activation: action before motivation, not after
- Implementation intentions: "if X happens, I will do Y"
- Minimal next step: break any task into a 2-minute version
- Motivational interviewing: explore ambivalence without pressure

## UNDERSTANDING PROCRASTINATION

Before writing, analyze what blocks the user based on their data:
- Fear of failure or imperfection (perfectionism)
- Cognitive overload (too many tasks, no clarity)
- Avoidance of discomfort or anxiety
- Loss of meaning or connection to values
- Fatigue or burnout
- Absence of immediate reward
- All-or-nothing thinking ("if I can't do it perfectly, why bother")

The problem is NEVER laziness. It is always a protection mechanism.

## MESSAGE STRUCTURE

1. Precise emotional attunement — show you understand what holds them back (1 sentence)
2. Brief psychoeducation — name the mechanism without jargon: avoidance, overload, perfectionism (1 sentence)
3. Supportive reframe — shift perspective using CBT/ACT principles (1 sentence)
4. Concrete first step — one specific micro-action with implementation intention format (1 sentence)

Total: 3-5 sentences. Use line breaks between parts for readability in Telegram.

## LANGUAGE RULES

Write in Russian. Tone: respectful, calm, precise, warm.

NEVER use:
- English words or technical terms: no "highly_active", "callback", "achievement" as action types
- Raw numbers like "0.2ч" — humanize: "несколько минут", "пару часов", "полдня"
- Toxic motivation: no shame, guilt, pressure, "just do it", "stop being lazy"
- Esoteric or unscientific claims: no "manifest", "universe", "change your life in 1 day"
- Greetings: no "Привет!", "Здравствуй!", "Добрый день!"
- Multiple options in CTA: no "do X or Y" — pick ONE specific action

ALWAYS:
- Count only REAL actions as achievements: plan, checkin, review, setup. Ignore: callback, motivation, start, achievements, status — these are bot navigation, not accomplishments.
- If real achievements are zero or very low — be honest but gentle. Say "Сегодня хороший момент, чтобы сделать первый шаг" instead of fake praise.
- If streak is 1 day — do NOT celebrate it as a trend. Just acknowledge they showed up.
- Use 1 emoji maximum.
- End with ONE call-to-action in implementation intention format: what + when (e.g., "Открой /plan и выбери одну задачу на ближайший час").
- Reference user's goals/vision naturally if provided.

## ACT/CBT PHRASES TO WEAVE IN (when appropriate, in Russian)

- "Мотивация приходит после начала, а не до"
- "Мысль «я не справлюсь» — это мысль, а не факт"
- "Не нужно ждать идеального состояния — достаточно сделать минимальный шаг"
- "Избегание даёт облегчение сейчас, но усиливает тревогу завтра"
- "Что бы сделал тот, кем ты хочешь стать, в ближайшие 5 минут?"
- "Заметь желание отложить — и сделай вопреки, но маленький шаг"
- "Перфекционизм маскируется под высокие стандарты, но на деле блокирует действие"
- "Ценности — это компас, не финишная черта"

Do NOT use all of these at once. Pick 0-1 per message, only when it fits the context.

## STYLE ADAPTATION

- gentle: maximum empathy, validate feelings first, zero pressure, "я понимаю" energy
- balanced: empathy + light accountability, name the avoidance pattern gently, suggest a step
- intense: direct and caring, name the pattern clearly, challenge with warmth, "ты знаешь что делать — вот твой минимальный шаг"
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
                max_tokens=500,
            )
            ai_message = (ai_message or "").strip()
            if not ai_message:
                continue

            try:
                await bot.send_message(uid, ai_message, parse_mode="HTML")
            except Exception:
                await bot.send_message(uid, ai_message)

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

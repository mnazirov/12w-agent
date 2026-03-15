"""APScheduler-based reminders for morning plan and evening check-in."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from app.services.mcp_orchestrator import MCPOrchestrator

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


async def _call_motivation_tool(
    mcp_orchestrator: MCPOrchestrator | None,
    mcp_client: MCPMotivationClient | None,
    tool_name: str,
    arguments: dict,
) -> dict:
    if mcp_orchestrator is not None:
        return await mcp_orchestrator.call_tool_on_server(
            "motivation",
            tool_name,
            arguments,
        )
    if mcp_client is None:
        return {"error": "MCP motivation client is not configured"}
    return await mcp_client.call_tool(tool_name, arguments)


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
    """Build user prompt with precise today's plan/checkin status."""
    eng = ctx.get("engagement", {})
    ach = ctx.get("achievements", {})
    today = ctx.get("today_actions", {})

    # --- Precise today data from MCP ---
    today_bd = today.get("today_breakdown", {})
    days_since = today.get("days_since", {})

    plan_today = "yes" if today_bd.get("plan", 0) > 0 else "no"
    checkin_today = "yes" if today_bd.get("checkin", 0) > 0 else "no"

    # days_since: int (0 = today) or None (never done)
    ds_plan = days_since.get("plan")
    ds_checkin = days_since.get("checkin")

    # Format for prompt: None → "never"
    days_without_plan = str(ds_plan) if ds_plan is not None else "never"
    days_without_checkin = str(ds_checkin) if ds_checkin is not None else "never"

    # --- Build prompt lines ---
    parts = [
        f"plan_today: {plan_today}",
        f"checkin_today: {checkin_today}",
        f"days_without_plan: {days_without_plan}",
        f"days_without_checkin: {days_without_checkin}",
        f"streak: {ach.get('current_streak', 0)} days",
        f"consistency: {ach.get('consistency', 0):.0%}",
        f"trend: {ach.get('trend', '?')}",
        f"engagement: {eng.get('engagement_level', '?')}",
        "",
        f"Today's actions: {today_bd if today_bd else 'none'}",
        f"Week plans: {ach.get('breakdown', {}).get('plan', 0)}, "
        f"checkins: {ach.get('breakdown', {}).get('checkin', 0)}, "
        f"reviews: {ach.get('breakdown', {}).get('review', 0)}",
        f"Style: {ctx.get('style', 'balanced')}",
    ]

    recent = ctx.get("recent_motivations", [])
    if recent:
        parts.append(
            "\nRecent motivations (do NOT repeat):\n"
            + "\n".join(f"- {m.get('message', '')[:100]}" for m in recent[:3])
        )

    return "\n".join(parts)


async def check_and_send_motivation(
    bot: Bot,
    mcp_client: MCPMotivationClient | None,
    openai_service,
    user_repo=None,
    mcp_orchestrator: MCPOrchestrator | None = None,
) -> None:
    """Check engagement and send motivation messages to eligible users."""
    logger.info("Motivation check started")
    try:
        users_data = await _call_motivation_tool(
            mcp_orchestrator,
            mcp_client,
            "get_users_needing_motivation",
            {},
        )
        raw_users = users_data.get("users", []) if isinstance(users_data, dict) else []
        users = [int(uid) for uid in raw_users if str(uid).isdigit()]
    except Exception as exc:
        logger.exception("Failed to fetch users needing motivation: %s", exc)
        return

    if not users:
        logger.info("No users need motivation right now")
        return

    for uid in users:
        try:
            ctx = await _call_motivation_tool(
                mcp_orchestrator,
                mcp_client,
                "generate_motivation_context",
                {"user_id": uid},
            )
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
            await _call_motivation_tool(
                mcp_orchestrator,
                mcp_client,
                "record_motivation_sent",
                {
                    "user_id": uid,
                    "message_type": str(ctx.get("recommended_type", "support")),
                    "engagement_level": str(engagement.get("engagement_level", "")),
                    "message": ai_message,
                },
            )
            logger.info("Motivation message sent to user %s", uid)
        except Exception as exc:
            logger.exception("Failed to process motivation for user %s: %s", uid, exc)
            continue


def register_motivation_job(
    scheduler: AsyncIOScheduler,
    bot: Bot,
    mcp_client: MCPMotivationClient | None,
    openai_service,
    user_repo=None,
    mcp_orchestrator: MCPOrchestrator | None = None,
) -> None:
    """Register periodic motivation check job in APScheduler."""
    scheduler.add_job(
        check_and_send_motivation,
        "interval",
        minutes=1,
        kwargs={
            "bot": bot,
            "mcp_client": mcp_client,
            "openai_service": openai_service,
            "user_repo": user_repo,
            "mcp_orchestrator": mcp_orchestrator,
        },
        id="motivation_check",
        replace_existing=True,
        misfire_grace_time=120,
    )


async def weekly_auto_report(
    bot: Bot,
    mcp_client: MCPMotivationClient | None,
    openai_service,
    user_repo=None,
    mcp_orchestrator: MCPOrchestrator | None = None,
):
    """Scheduler job: автоматический еженедельный отчёт (воскресенье)."""
    from app.services.pipeline_service import run_analytics_pipeline

    logger.info("Weekly auto-report started")

    try:
        data = await _call_motivation_tool(
            mcp_orchestrator,
            mcp_client,
            "get_users_needing_motivation",
            {},
        )
        user_ids = data.get("users", []) if isinstance(data, dict) else []
    except Exception as exc:
        logger.error("Cannot get user list for weekly report: %s", exc)
        return

    # Also include users who have motivation enabled but might not need motivation now
    # For simplicity, run for all users who have any config
    if not user_ids:
        logger.info("No users for weekly report")
        return

    for uid in user_ids:
        try:
            vision = None
            if user_repo:
                try:
                    v = await user_repo.get_vision(uid)
                    if v:
                        vision = getattr(v, "vision", None)
                except Exception:
                    pass

            result = await run_analytics_pipeline(
                mcp_client=mcp_client,
                openai_service=openai_service,
                user_id=uid,
                days=7,
                vision=vision,
                mcp_orchestrator=mcp_orchestrator,
            )

            if not result.get("success"):
                continue

            ai = result.get("ai_insights", "")
            score = result.get("completion_score", 0)
            score_bar = "█" * int(score * 10) + "░" * (10 - int(score * 10))

            text = (
                f"📊 <b>Еженедельная сводка</b>\n\n"
                f"Выполнение: {score_bar} {score:.0%}\n"
            )
            if ai:
                text += f"\n{ai}\n"
            text += "\nПодробнее: /report"

            try:
                await bot.send_message(uid, text, parse_mode="HTML")
            except Exception:
                await bot.send_message(uid, text)

            logger.info("Weekly report sent to user %s", uid)

        except Exception as exc:
            logger.error("Weekly report failed for user %s: %s", uid, exc)


def register_weekly_report_job(
    scheduler,
    bot: Bot,
    mcp_client: MCPMotivationClient | None,
    openai_service,
    user_repo=None,
    mcp_orchestrator: MCPOrchestrator | None = None,
):
    """Register weekly report cron job (Sunday 20:00)."""
    scheduler.add_job(
        weekly_auto_report,
        "cron",
        day_of_week="sun",
        hour=20,
        minute=0,
        kwargs={
            "bot": bot,
            "mcp_client": mcp_client,
            "openai_service": openai_service,
            "user_repo": user_repo,
            "mcp_orchestrator": mcp_orchestrator,
        },
        id="weekly_auto_report",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info("Weekly auto-report registered (Sunday 20:00)")

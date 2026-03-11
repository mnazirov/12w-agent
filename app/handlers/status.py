"""Handler for /status — progress summary with sprint info."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.keyboards import main_menu_kb
from db.base import get_session_factory
from db.repos import (
    get_active_goals,
    get_active_sprint,
    get_checkin_streak,
    get_current_week_number,
    get_or_create_user,
    get_sprint_days_remaining,
    get_vision,
    get_weekly_stats,
    is_sprint_finished,
)

logger = logging.getLogger(__name__)
router = Router(name="status")


def _progress_bar(pct: int, width: int = 10) -> str:
    filled = round(pct / 100 * width)
    empty = width - filled
    return "▓" * filled + "░" * empty


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    if not message.from_user:
        return

    async with get_session_factory()() as session:
        user = await get_or_create_user(
            session, message.from_user.id, message.from_user.first_name
        )

        sprint = await get_active_sprint(session, user.id)
        goals = await get_active_goals(session, user.id)

        if not sprint and not goals:
            await message.answer(
                "Пока нет активного марафона. Начни с /setup",
                reply_markup=main_menu_kb(),
            )
            return

        if not sprint:
            await message.answer(
                "Цели есть, но марафон не запущен.\n"
                "Используй /setup чтобы начать 12-недельный марафон.",
                reply_markup=main_menu_kb(),
            )
            return

        # Sprint data
        today = date.today()
        week_num = get_current_week_number(sprint, today)
        days_left = get_sprint_days_remaining(sprint, today)
        finished = is_sprint_finished(sprint, today)

        # Weekly stats (current sprint week: Mon–Sun)
        sprint_week_start = sprint.start_date + timedelta(weeks=week_num - 1)
        sprint_week_end = sprint_week_start + timedelta(days=6)
        stats = await get_weekly_stats(
            session, user.id,
            sprint_week_start,
            min(sprint_week_end, today),
        )

        # Streak
        streak = await get_checkin_streak(session, user.id)

        # Vision
        vision_row = await get_vision(session, user.id)

    # Build message
    start_fmt = sprint.start_date.strftime("%d.%m.%Y")
    end_fmt = sprint.end_date.strftime("%d.%m.%Y")

    lines: list[str] = []

    if finished:
        lines.append("🏁 *Марафон завершён!*\n")
        lines.append(f"Период: {start_fmt} — {end_fmt}\n")
        lines.append("Поздравляю! Начни новый марафон: /setup\n")
    else:
        lines.append(f"📊 *Прогресс — неделя {week_num}/12*\n")

        # Sprint timeline
        week_pct = round(week_num / 12 * 100)
        lines.append(f"12 недель: {_progress_bar(week_pct)} {week_pct}%")
        lines.append(f"📅 Старт: {start_fmt}")
        lines.append(f"🏁 Финиш: {end_fmt}")
        lines.append(f"⏳ Осталось: {days_left} дн.\n")

    # Lead actions this week
    planned = stats["planned"]
    completed = stats["completed"]
    score_pct = (completed * 100 // max(1, planned)) if planned else 0
    lines.append(
        f"*Lead actions (неделя {week_num}):* {completed}/{planned} "
        f"({score_pct}%) {_progress_bar(score_pct)}\n"
    )

    # Goals list
    if goals:
        lines.append("*Цели:*")
        for i, g in enumerate(goals, 1):
            metric_info = f" — {g.metric}" if g.metric else ""
            lines.append(f"  {i}. {g.title}{metric_info}")
        lines.append("")

    # Streak
    if streak > 0:
        lines.append(f"🔥 Полоса чек-инов: {streak} дн.\n")

    # Vision reminder
    if vision_row:
        lines.append(f"🌟 *Твоё видение:* _{vision_row.vision[:200]}_")

    await message.answer("\n".join(lines), parse_mode="Markdown")

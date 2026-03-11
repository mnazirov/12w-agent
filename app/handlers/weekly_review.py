"""Handler for /weekly_review — weekly scoring and AI reflection."""
from __future__ import annotations

import logging
from datetime import date

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.services.review_service import (
    format_review_message,
    generate_review,
    weekly_scoring,
)
from db.base import get_session_factory
from db.repos import (
    get_active_goals,
    get_active_sprint,
    get_current_week_number,
    get_or_create_user,
    get_sprint_days_remaining,
)

logger = logging.getLogger(__name__)
router = Router(name="weekly_review")


@router.message(Command("weekly_review"))
async def cmd_weekly_review(message: Message) -> None:
    if not message.from_user:
        return

    async with get_session_factory()() as session:
        user = await get_or_create_user(
            session, message.from_user.id, message.from_user.first_name
        )
        goals = await get_active_goals(session, user.id)
        if not goals:
            await message.answer("Сначала настрой цели: /setup")
            return

        sprint = await get_active_sprint(session, user.id)
        week_num = get_current_week_number(sprint) if sprint else 1

        await message.answer("⏳ Считаю результаты недели…")

        try:
            stats = await weekly_scoring(session, user.id)
            review = await generate_review(session, user.id, week_number=week_num)
            await session.commit()
        except Exception as e:
            logger.exception("Weekly review failed: %s", e)
            await message.answer("Ошибка при формировании обзора. Попробуй позже.")
            return

    text = format_review_message(review, stats)

    # Header with sprint info
    header = f"📅 *Неделя {week_num} из 12*"
    if sprint:
        days_left = get_sprint_days_remaining(sprint)
        end_fmt = sprint.end_date.strftime("%d.%m.%Y")
        header += f"  (до {end_fmt}, осталось {days_left} дн.)"
    header += "\n\n"

    # Footer with milestone reminders
    footer = ""
    if week_num == 6:
        footer = (
            "\n\n⚠️ *Середина 12 недель!* Самое время пересмотреть цели "
            "и убедиться, что ты на верном пути. Подумай, нужны ли корректировки."
        )
    elif week_num == 12:
        footer = (
            "\n\n🏁 *Последняя неделя!* Финальный рывок. "
            "Вспомни, зачем ты начал — и доведи до конца."
        )

    await message.answer(header + text + footer, parse_mode="Markdown")

"""Handler for /plan — daily plan generation with implementation intentions."""
from __future__ import annotations

import logging
from datetime import date

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.keyboards import plan_action_kb
from app.services.planning_service import format_plan_message, generate_daily_plan
from db.base import get_session_factory
from db.repos import get_active_goals, get_or_create_user

logger = logging.getLogger(__name__)
router = Router(name="plan")


@router.message(Command("plan"))
async def cmd_plan(message: Message) -> None:
    if not message.from_user:
        return

    async with get_session_factory()() as session:
        user = await get_or_create_user(
            session, message.from_user.id, message.from_user.first_name
        )
        goals = await get_active_goals(session, user.id)
        if not goals:
            await message.answer(
                "Сначала настрой цели: /setup\n"
                "Без целей план не построить."
            )
            return

        await message.answer("⏳ Генерирую план на сегодня…")

        try:
            plan = await generate_daily_plan(session, user.id)
            await session.commit()
        except Exception as e:
            logger.exception("Plan generation failed: %s", e)
            await message.answer("Ошибка при создании плана. Попробуй позже.")
            return

    plan_text = format_plan_message(plan)
    await message.answer(plan_text, reply_markup=plan_action_kb(), parse_mode="Markdown")


@router.callback_query(F.data == "plan_accept")
async def cb_plan_accept(callback: CallbackQuery) -> None:
    await callback.answer("План принят! Вперёд 💪")
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(
            "План активирован. Вечером отметь результаты: /checkin"
        )


@router.callback_query(F.data == "plan_regenerate")
async def cb_plan_regenerate(callback: CallbackQuery) -> None:
    await callback.answer("Генерирую другой план…")
    if not callback.from_user or not callback.message:
        return

    async with get_session_factory()() as session:
        user = await get_or_create_user(
            session, callback.from_user.id, callback.from_user.first_name
        )
        try:
            plan = await generate_daily_plan(session, user.id)
            await session.commit()
        except Exception as e:
            logger.exception("Plan regeneration failed: %s", e)
            await callback.message.answer("Ошибка. Попробуй /plan ещё раз.")
            return

    plan_text = format_plan_message(plan)
    await callback.message.answer(plan_text, reply_markup=plan_action_kb(), parse_mode="Markdown")

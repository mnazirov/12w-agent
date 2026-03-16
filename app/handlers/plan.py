"""Handler for /plan — daily plan generation with implementation intentions."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.keyboards import plan_action_kb
from app.services.planning_service import format_plan_message, generate_daily_plan
from app.states import PlanStates
from db.base import get_session_factory
from db.repos import (
    get_active_goals,
    get_or_create_user,
    get_user_city,
    update_user_city,
)

logger = logging.getLogger(__name__)
router = Router(name="plan")


async def _send_generated_plan(
    message: Message,
    user_id: int,
    mcp_orchestrator=None,
    city_override: str | None = None,
    loading_text: str = "⏳ Генерирую план на сегодня…",
) -> None:
    await message.answer(loading_text)
    notices: list[str] = []

    async with get_session_factory()() as session:
        try:
            plan = await generate_daily_plan(
                session,
                user_id,
                mcp_orchestrator=mcp_orchestrator,
                city_override=city_override,
                notices=notices,
            )
            await session.commit()
        except Exception as exc:
            logger.exception("Plan generation failed: %s", exc)
            await message.answer("Ошибка при создании плана. Попробуй позже.")
            return

    for notice in notices:
        await message.answer(notice)

    plan_text = format_plan_message(plan)
    await message.answer(plan_text, reply_markup=plan_action_kb(), parse_mode="Markdown")


@router.message(Command("plan"))
async def cmd_plan(
    message: Message,
    state: FSMContext,
    mcp_orchestrator=None,
) -> None:
    if not message.from_user:
        return

    text = (message.text or "").strip()
    parts = text.split(maxsplit=1)
    one_time_city = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None

    async with get_session_factory()() as session:
        user = await get_or_create_user(
            session,
            message.from_user.id,
            message.from_user.first_name,
        )
        goals = await get_active_goals(session, user.id)
        if not goals:
            await message.answer(
                "Сначала настрой цели: /setup\n"
                "Без целей план не построить."
            )
            return

        saved_city = await get_user_city(session, user.id)
        if one_time_city is None and saved_city is None:
            await state.set_state(PlanStates.waiting_city)
            await message.answer(
                "Для учёта погоды укажи твой город.\n"
                "Отправь название (например: Москва):"
            )
            return

        user_id = user.id

    await state.clear()
    await _send_generated_plan(
        message,
        user_id=user_id,
        mcp_orchestrator=mcp_orchestrator,
        city_override=one_time_city,
    )


@router.message(PlanStates.waiting_city)
async def on_plan_city(
    message: Message,
    state: FSMContext,
    mcp_orchestrator=None,
) -> None:
    if not message.from_user:
        return

    city = (message.text or "").strip()
    if not city or city.startswith("/"):
        await message.answer("Нужен именно город текстом. Пример: Санкт-Петербург")
        return

    async with get_session_factory()() as session:
        user = await get_or_create_user(
            session,
            message.from_user.id,
            message.from_user.first_name,
        )
        goals = await get_active_goals(session, user.id)
        if not goals:
            await message.answer(
                "Сначала настрой цели: /setup\n"
                "Без целей план не построить."
            )
            await state.clear()
            return

        await update_user_city(session, user.id, city)
        await session.commit()
        user_id = user.id

    await state.clear()
    await message.answer(f"Город сохранён: {city}")
    await _send_generated_plan(
        message,
        user_id=user_id,
        mcp_orchestrator=mcp_orchestrator,
    )


@router.callback_query(F.data == "plan_accept")
async def cb_plan_accept(callback: CallbackQuery) -> None:
    await callback.answer("План принят! Вперёд 💪")
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(
            "План активирован. Вечером отметь результаты: /checkin"
        )


@router.callback_query(F.data == "plan_regenerate")
async def cb_plan_regenerate(callback: CallbackQuery, mcp_orchestrator=None) -> None:
    await callback.answer("Генерирую другой план…")
    if not callback.from_user or not callback.message:
        return

    async with get_session_factory()() as session:
        user = await get_or_create_user(
            session,
            callback.from_user.id,
            callback.from_user.first_name,
        )
        user_id = user.id

    await _send_generated_plan(
        callback.message,
        user_id=user_id,
        mcp_orchestrator=mcp_orchestrator,
        loading_text="⏳ Генерирую другой план…",
    )

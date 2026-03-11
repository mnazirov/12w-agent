"""Handler for /setup — FSM flow: vision → why → goals → lead actions → confirm."""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.keyboards import setup_confirm_kb, skip_kb
from app.states import SetupStates
from db.base import get_session_factory
from db.repos import (
    add_goals,
    create_sprint,
    deactivate_all_goals,
    get_or_create_user,
    upsert_vision,
    upsert_weekly_plan,
)

logger = logging.getLogger(__name__)
router = Router(name="setup")


def _parse_list(text: str) -> list[str]:
    """Parse a user message into a list of items (newlines, commas, numbered)."""
    text = (text or "").strip()
    if not text:
        return []
    parts = re.split(r"[\n;]+", text)
    items: list[str] = []
    for p in parts:
        p = p.strip()
        p = re.sub(r"^\s*[\d]+[.)]\s*", "", p)
        p = re.sub(r"^\s*[-*•]\s*", "", p)
        if p:
            items.append(p)
    return items


# ── Step 1: Start setup ─────────────────────────────────────────────────

@router.message(Command("setup"))
async def cmd_setup(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    await state.clear()
    await state.set_state(SetupStates.vision)
    await message.answer(
        "🎯 *Шаг 1 из 4: Видение*\n\n"
        "Опиши своё видение результата через 12 недель.\n"
        "Как будет выглядеть твоя жизнь, когда цели достигнуты?\n\n"
        "_Пример: «Я запустил продукт, набрал первых 100 пользователей, "
        "чувствую уверенность и энергию»_",
        parse_mode="Markdown",
    )


# ── Step 2: Capture vision, ask for why ──────────────────────────────────

@router.message(SetupStates.vision)
async def on_vision(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Пожалуйста, опиши своё видение текстом.")
        return

    await state.update_data(vision=text)
    await state.set_state(SetupStates.why)
    await message.answer(
        "💡 *Шаг 2 из 4: Почему это важно?*\n\n"
        "Почему эти результаты важны для тебя?\n"
        "Что изменится в твоей жизни?\n\n"
        "_Чем глубже «почему», тем сильнее мотивация в трудные дни._",
        parse_mode="Markdown",
    )


# ── Step 3: Capture why, ask for goals ───────────────────────────────────

@router.message(SetupStates.why)
async def on_why(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Пожалуйста, напиши, почему это важно.")
        return

    await state.update_data(why=text)
    await state.set_state(SetupStates.goals)
    await message.answer(
        "🎯 *Шаг 3 из 4: Цели*\n\n"
        "Назови 1–3 конкретные цели на 12 недель.\n"
        "Желательно с измеримыми метриками.\n\n"
        "_Пример:_\n"
        "_1. Запустить MVP продукта (метрика: 100 регистраций)_\n"
        "_2. Читать 30 минут ежедневно (метрика: 60 дней подряд)_\n"
        "_3. Бегать 3 раза в неделю (метрика: 36 пробежек)_",
        parse_mode="Markdown",
    )


# ── Step 4: Capture goals, ask for lead actions ─────────────────────────

@router.message(SetupStates.goals)
async def on_goals(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    goals = _parse_list(text)
    if not goals:
        await message.answer("Не нашёл целей. Напиши каждую цель с новой строки.")
        return

    await state.update_data(goals=goals)
    await state.set_state(SetupStates.lead_actions)
    await message.answer(
        "📌 *Шаг 4 из 4: Еженедельные действия*\n\n"
        "Какие конкретные действия каждую неделю приведут к целям?\n"
        "Это «ведущие показатели» — то, что ты контролируешь.\n\n"
        "_Пример:_\n"
        "_- Написать 2 фичи для MVP_\n"
        "_- Читать 30 мин каждый день_\n"
        "_- Три пробежки по 30 мин_",
        parse_mode="Markdown",
    )


# ── Step 5: Capture lead actions, show summary for confirmation ──────────

@router.message(SetupStates.lead_actions)
async def on_lead_actions(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    actions = _parse_list(text)
    if not actions:
        await message.answer("Не нашёл действий. Напиши каждое с новой строки.")
        return

    await state.update_data(lead_actions=actions)
    await state.set_state(SetupStates.confirm)

    data = await state.get_data()
    summary = (
        "📋 *Проверь настройку:*\n\n"
        f"*Видение:* {data['vision']}\n\n"
        f"*Почему:* {data['why']}\n\n"
        "*Цели:*\n" + "\n".join(f"  {i}. {g}" for i, g in enumerate(data['goals'], 1)) + "\n\n"
        "*Еженедельные действия:*\n" + "\n".join(f"  • {a}" for a in data['lead_actions'])
    )
    await message.answer(summary, reply_markup=setup_confirm_kb(), parse_mode="Markdown")


# ── Confirm: Save ────────────────────────────────────────────────────────

@router.callback_query(SetupStates.confirm, F.data == "setup_save")
async def on_setup_save(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer("Сохраняю…")
    if not callback.from_user:
        return

    data = await state.get_data()

    async with get_session_factory()() as session:
        user = await get_or_create_user(
            session, callback.from_user.id, callback.from_user.first_name
        )

        # Save vision & why
        await upsert_vision(
            session,
            user_id=user.id,
            vision=data["vision"],
            why_text=data["why"],
        )

        # Create 12-week sprint
        sprint = await create_sprint(session, user.id)

        # Deactivate old goals, add new
        await deactivate_all_goals(session, user.id)
        goal_dicts = [{"title": g} for g in data["goals"]]
        await add_goals(session, user.id, goal_dicts, deadline=sprint.end_date)

        # Save week 1 plan
        await upsert_weekly_plan(
            session,
            user_id=user.id,
            week_number=1,
            year=sprint.start_date.year,
            lead_actions=data["lead_actions"],
        )

        await session.commit()

    await state.clear()
    if callback.message:
        start_fmt = sprint.start_date.strftime("%d.%m.%Y")
        end_fmt = sprint.end_date.strftime("%d.%m.%Y")
        await callback.message.answer(
            f"✅ Всё сохранено!\n\n"
            f"📅 *Марафон:* {start_fmt} — {end_fmt} (12 недель)\n\n"
            f"Теперь составь план на сегодня: /plan",
            parse_mode="Markdown",
        )


# ── Confirm: Edit (restart setup) ───────────────────────────────────────

@router.callback_query(SetupStates.confirm, F.data == "setup_edit")
async def on_setup_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(SetupStates.vision)
    if callback.message:
        await callback.message.answer(
            "Давай с начала.\n\n"
            "🎯 *Шаг 1: Видение* — опиши своё видение результата через 12 недель.",
            parse_mode="Markdown",
        )

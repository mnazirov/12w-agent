"""Handler for /start command and main menu callbacks."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.keyboards import main_menu_kb
from db.base import get_session_factory
from db.repos import get_active_sprint, get_or_create_user, is_sprint_finished

logger = logging.getLogger(__name__)
router = Router(name="start")


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    if not message.from_user:
        return

    async with get_session_factory()() as session:
        user = await get_or_create_user(
            session,
            telegram_id=message.from_user.id,
            first_name=message.from_user.first_name,
        )
        sprint = await get_active_sprint(session, user.id)
        has_sprint = sprint is not None and not is_sprint_finished(sprint)
        await session.commit()

    name = message.from_user.first_name or ""
    greeting = (
        f"Привет{f', {name}' if name else ''}! "
        "Я твой помощник по методике «12 недель в году».\n\n"
        "Помогу с целями, планом на день, чек-инами, обзорами и аналитикой прогресса.\n\n"
        "*Команды:*\n"
        "/setup — настроить видение и цели\n"
        "/plan — план на сегодня\n"
        "/checkin — вечерний чек-ин\n"
        "/weekly\\_review — недельный обзор\n"
        "/status — прогресс\n"
        "/report — аналитический отчёт за 7 дней\n"
        "/motivation — настройки мотивации\n"
        "/achievements — сводка достижений\n"
        "Свободный текст — чат с AI-помощником\n\n"
        "Или выбери действие кнопкой:"
    )
    await message.answer(
        greeting, reply_markup=main_menu_kb(has_active_sprint=has_sprint), parse_mode="Markdown"
    )


# ── Menu button callbacks ────────────────────────────────────────────────

@router.callback_query(F.data == "cmd_setup")
async def cb_setup(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Начинаем настройку! Используй /setup"
        )


@router.callback_query(F.data == "cmd_plan")
async def cb_plan(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.answer("Генерирую план… Используй /plan")


@router.callback_query(F.data == "cmd_checkin")
async def cb_checkin(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.answer("Начинаем чек-ин! Используй /checkin")


@router.callback_query(F.data == "cmd_status")
async def cb_status(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.answer("Загружаю статус… Используй /status")


@router.callback_query(F.data == "cmd_weekly_review")
async def cb_weekly_review(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.answer("Недельный обзор! Используй /weekly_review")

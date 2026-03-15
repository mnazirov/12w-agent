"""Telegram handlers for connecting/disconnecting Google account."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.keyboards import (
    google_connect_keyboard,
    google_disconnect_confirm_keyboard,
    google_reconnect_keyboard,
    google_status_keyboard,
)
from db.base import get_session_factory
from db.repos import get_user_by_telegram_id

logger = logging.getLogger(__name__)
router = Router(name="google_auth")


def _google_not_configured_text() -> str:
    return "Google OAuth не настроен администратором."


@router.message(Command("connect_google"))
async def cmd_connect_google(message: Message, google_auth_service=None) -> None:
    if not message.from_user:
        return
    if google_auth_service is None:
        await message.answer(_google_not_configured_text())
        return

    async with get_session_factory()() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
    if user is None:
        await message.answer("Сначала выполните /start для регистрации.")
        return

    if await google_auth_service.is_connected(user.id):
        email = await google_auth_service.get_connected_email(user.id)
        email_text = f" ({email})" if email else ""
        await message.answer(
            f"Google-аккаунт уже подключён{email_text}.\n\n"
            "Хотите переподключить с другим аккаунтом?",
            reply_markup=google_reconnect_keyboard(),
        )
        return

    auth_url = google_auth_service.generate_auth_url(message.from_user.id)
    await message.answer(
        "Для работы с Google Calendar подключите аккаунт.\n\n"
        "Нажмите кнопку ниже — откроется страница Google для выдачи доступа:",
        reply_markup=google_connect_keyboard(auth_url),
    )


@router.message(Command("disconnect_google"))
async def cmd_disconnect_google(message: Message, google_auth_service=None) -> None:
    if not message.from_user:
        return
    if google_auth_service is None:
        await message.answer(_google_not_configured_text())
        return

    async with get_session_factory()() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
    if user is None or not await google_auth_service.is_connected(user.id):
        await message.answer("Google-аккаунт не подключён.")
        return

    email = await google_auth_service.get_connected_email(user.id)
    email_text = f" ({email})" if email else ""
    await message.answer(
        f"Отключить Google-аккаунт{email_text}?\n\n"
        "Бот потеряет доступ к вашему календарю.",
        reply_markup=google_disconnect_confirm_keyboard(),
    )


@router.callback_query(F.data == "google_disconnect")
async def on_disconnect_click(callback: CallbackQuery, google_auth_service=None) -> None:
    if google_auth_service is None:
        await callback.answer(_google_not_configured_text(), show_alert=False)
        return
    if callback.message:
        await callback.message.edit_text(
            "Отключить Google-аккаунт?\n\n"
            "Бот потеряет доступ к вашему календарю.",
            reply_markup=google_disconnect_confirm_keyboard(),
        )
    await callback.answer()


@router.callback_query(F.data == "google_disconnect_confirm")
async def on_disconnect_confirm(callback: CallbackQuery, google_auth_service=None) -> None:
    if not callback.from_user:
        await callback.answer()
        return
    if google_auth_service is None:
        await callback.answer(_google_not_configured_text(), show_alert=False)
        return

    async with get_session_factory()() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)

    if user is not None:
        await google_auth_service.revoke_and_delete(user.id)

    if callback.message:
        await callback.message.edit_text("🔓 Google-аккаунт отключён.")
    await callback.answer()


@router.callback_query(F.data == "google_disconnect_cancel")
async def on_disconnect_cancel(callback: CallbackQuery) -> None:
    if callback.message:
        await callback.message.edit_text("Отключение отменено.")
    await callback.answer()


@router.callback_query(F.data == "google_reconnect")
async def on_reconnect(callback: CallbackQuery, google_auth_service=None) -> None:
    if not callback.from_user:
        await callback.answer()
        return
    if google_auth_service is None:
        await callback.answer(_google_not_configured_text(), show_alert=False)
        return

    async with get_session_factory()() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)

    if user is None:
        if callback.message:
            await callback.message.edit_text("Сначала выполните /start для регистрации.")
        await callback.answer()
        return

    await google_auth_service.revoke_and_delete(user.id)
    auth_url = google_auth_service.generate_auth_url(callback.from_user.id)

    if callback.message:
        await callback.message.edit_text(
            "Старый аккаунт отключён. Подключите новый:",
            reply_markup=google_connect_keyboard(auth_url),
        )
    await callback.answer()


@router.message(Command("google_status"))
async def cmd_google_status(message: Message, google_auth_service=None) -> None:
    if not message.from_user:
        return
    if google_auth_service is None:
        await message.answer(_google_not_configured_text())
        return

    async with get_session_factory()() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)

    if user is None or not await google_auth_service.is_connected(user.id):
        await message.answer(
            "❌ Google-аккаунт не подключён.\n\n"
            "Подключите командой /connect_google",
        )
        return

    email = await google_auth_service.get_connected_email(user.id)
    expiry = await google_auth_service.get_token_expiry(user.id)
    expiry_text = expiry.strftime("%d.%m.%Y %H:%M") if expiry else "—"

    await message.answer(
        f"✅ Google подключён: {email or 'email неизвестен'}\n"
        f"Токен действителен до: {expiry_text}",
        reply_markup=google_status_keyboard(),
    )

"""Fallback handler — free-form AI chat with goal context."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import Message

from app.services.openai_service import call_text
from db.base import get_session_factory
from db.repos import get_active_goals, get_or_create_user

logger = logging.getLogger(__name__)
router = Router(name="chat")


@router.message(F.text)
async def on_text(message: Message) -> None:
    """Catch-all for text messages that don't match any command or FSM state."""
    if not message.from_user:
        return
    text = (message.text or "").strip()
    if not text:
        return

    async with get_session_factory()() as session:
        user = await get_or_create_user(
            session, message.from_user.id, message.from_user.first_name
        )
        goals = await get_active_goals(session, user.id)

    goal_titles = [g.title for g in goals] if goals else None

    await message.answer("💬")  # typing indicator fallback

    try:
        reply = await call_text(
            user_message=text,
            goals=goal_titles,
            first_name=message.from_user.first_name,
        )
        if reply:
            await message.answer(reply)
        else:
            await message.answer("Не удалось получить ответ. Попробуй ещё раз.")
    except Exception as e:
        logger.exception("Chat AI call failed: %s", e)
        await message.answer("Ошибка при запросе к AI. Попробуй позже.")

"""Fallback handler for free-form chat with multi-turn context."""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.middleware.rate_limit import ChatRateLimiter
from app.services.chat_context_service import ChatContextService
from app.services.openai_service import generate_chat, load_template
from db.base import get_session_factory
from db.repos import get_or_create_user

logger = logging.getLogger(__name__)
router = Router(name="chat")


@router.message(Command("clear"))
async def cmd_clear_chat(
    message: Message,
    chat_context_service: ChatContextService | None = None,
) -> None:
    """Reset free chat session context."""
    if not message.from_user:
        return
    if chat_context_service is None:
        await message.answer("Сервис контекста чата сейчас недоступен. Попробуй позже.")
        return

    async with get_session_factory()() as session:
        user = await get_or_create_user(
            session,
            message.from_user.id,
            message.from_user.first_name,
        )
        await session.commit()

    await chat_context_service.clear_session(user.id)
    await message.answer(
        "Контекст чата очищен.\n\n"
        "Цели и прогресс в памяти сохранены."
    )


@router.message()
async def on_text(
    message: Message,
    mcp_orchestrator=None,
    chat_context_service: ChatContextService | None = None,
    chat_rate_limiter: ChatRateLimiter | None = None,
) -> None:
    """Catch-all for free chat messages."""
    if not message.from_user:
        return

    text = ((message.text or message.caption) or "").strip()
    if not text:
        await message.answer("Пока я понимаю только текстовые сообщения 📝")
        return
    if message.text and text.startswith("/"):
        await message.answer("Неизвестная команда. Используй /start для списка команд.")
        return

    if chat_rate_limiter is not None and not chat_rate_limiter.check(message.from_user.id):
        await message.answer("Слишком много сообщений. Подожди немного ⏳")
        return

    async with get_session_factory()() as session:
        user = await get_or_create_user(
            session,
            message.from_user.id,
            message.from_user.first_name,
        )
        await session.commit()

    await message.answer("💬")  # typing indicator fallback

    try:
        previous_response_id = None
        user_context = ""
        if chat_context_service is not None:
            previous_response_id = await chat_context_service.get_previous_response_id(user.id)
            user_context = await chat_context_service.build_user_context(user.id)

        system_prompt = load_template("system")
        reply, response_id = await generate_chat(
            user_message=text,
            system_prompt=system_prompt,
            user_context=user_context,
            previous_response_id=previous_response_id,
            mcp_orchestrator=mcp_orchestrator,
            use_tools=bool(mcp_orchestrator),
            tool_server_names=["calendar", "weather"],
            user_id=user.id,
        )
        if chat_context_service is not None:
            if response_id:
                await chat_context_service.save_response_id(user.id, response_id)
            elif previous_response_id is not None:
                # Avoid continuing from stale branch if response id wasn't persisted.
                await chat_context_service.clear_session(user.id)

        if reply:
            await send_long_message(message, reply)
        else:
            await message.answer("Не удалось получить ответ. Попробуй ещё раз.")
    except Exception as e:
        logger.exception("Chat AI call failed: %s", e)
        await message.answer("Ошибка при запросе к AI. Попробуй позже.")


async def send_long_message(
    message: Message,
    text: str,
    max_length: int = 4096,
) -> None:
    """Split long messages by paragraph/word boundaries for Telegram limits."""
    if len(text) <= max_length:
        await message.answer(text)
        return

    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= max_length:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        remaining = paragraph
        while len(remaining) > max_length:
            split_at = remaining.rfind("\n", 0, max_length)
            if split_at <= 0:
                split_at = remaining.rfind(" ", 0, max_length)
            if split_at <= 0:
                split_at = max_length
            chunks.append(remaining[:split_at].strip())
            remaining = remaining[split_at:].strip()
        current = remaining

    if current:
        chunks.append(current)

    for part in chunks:
        if part:
            await message.answer(part)

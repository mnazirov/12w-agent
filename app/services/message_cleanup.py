"""Helpers for deleting the previous bot reply when a new command arrives."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

logger = logging.getLogger(__name__)

_LAST_BOT_MESSAGE_BY_CHAT: dict[int, int] = {}
_LOCK = asyncio.Lock()


async def remember_last_bot_message(chat_id: int, message_id: int) -> None:
    """Store the latest bot message id for a chat."""
    async with _LOCK:
        _LAST_BOT_MESSAGE_BY_CHAT[chat_id] = message_id


async def pop_last_bot_message(chat_id: int) -> int | None:
    """Read and remove stored bot message id for a chat."""
    async with _LOCK:
        return _LAST_BOT_MESSAGE_BY_CHAT.pop(chat_id, None)


async def delete_last_bot_message(bot: Bot, chat_id: int) -> None:
    """Delete the previous tracked bot message in chat if possible."""
    previous_message_id = await pop_last_bot_message(chat_id)
    if previous_message_id is None:
        return

    try:
        await bot.delete_message(chat_id=chat_id, message_id=previous_message_id)
    except TelegramBadRequest as exc:
        # Common when the message is already deleted or out of delete window.
        logger.debug(
            "Skipping previous bot message delete chat=%s message=%s: %s",
            chat_id,
            previous_message_id,
            exc,
        )
    except Exception as exc:
        logger.debug(
            "Failed to delete previous bot message chat=%s message=%s: %s",
            chat_id,
            previous_message_id,
            exc,
        )


class TrackingBot(Bot):
    """Bot that remembers every sent text message as the last assistant reply."""

    async def send_message(self, *args, **kwargs) -> Message:
        sent = await super().send_message(*args, **kwargs)
        await remember_last_bot_message(chat_id=sent.chat.id, message_id=sent.message_id)
        return sent

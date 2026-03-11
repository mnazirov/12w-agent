"""Aiogram middleware for non-blocking activity tracking via MCP."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.services.mcp_client import MCPMotivationClient

logger = logging.getLogger(__name__)


class ActivityTrackerMiddleware(BaseMiddleware):
    """Capture incoming updates and log lightweight activity events."""

    _CMD_MAP = {
        "/start": "start",
        "/setup": "setup",
        "/plan": "plan",
        "/checkin": "checkin",
        "/weekly_review": "review",
        "/status": "status",
        "/motivation": "motivation",
        "/achievements": "achievements",
    }

    def __init__(self, mcp_client: MCPMotivationClient) -> None:
        self.mcp = mcp_client

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user_id: int | None = None
        action = "unknown"
        details = ""

        if isinstance(event, Message):
            user_id = event.from_user.id if event.from_user else None
            text = (event.text or "").strip()
            if text.startswith("/"):
                command = text.split()[0].split("@")[0]
                action = self._CMD_MAP.get(command, "command")
            else:
                action = "chat"
            details = text[:150]
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id if event.from_user else None
            action = "callback"
            details = (event.data or "")[:150]

        if user_id is not None:
            asyncio.create_task(self._safe_log(user_id=user_id, action=action, details=details))

        return await handler(event, data)

    async def _safe_log(self, user_id: int, action: str, details: str) -> None:
        """Log activity without affecting handler execution path."""
        try:
            await self.mcp.log_activity(user_id=user_id, action=action, details=details)
        except Exception as exc:
            logger.debug("Activity tracking skipped for %s: %s", user_id, exc)

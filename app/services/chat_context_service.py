"""Chat context management for free-form fallback chat."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import MEMORY_CONTEXT_MAX_TOKENS
from app.services import memory_service
from db import repos

logger = logging.getLogger(__name__)


class ChatContextService:
    """Manage multi-turn session pointer and persistent user context."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        session_timeout_minutes: int = 120,
        memory_context_max_tokens: int = MEMORY_CONTEXT_MAX_TOKENS,
    ) -> None:
        self._session_factory = session_factory
        self._session_timeout = timedelta(minutes=session_timeout_minutes)
        self._memory_context_max_tokens = memory_context_max_tokens

    async def get_previous_response_id(self, user_id: int) -> str | None:
        """Return response id for Responses API continuation or None for new session."""
        async with self._session_factory() as session:
            last_activity = await repos.get_last_chat_activity(session, user_id)
            if last_activity is None:
                return None

            if last_activity.tzinfo is None:
                last_activity = last_activity.replace(tzinfo=timezone.utc)

            elapsed = datetime.now(timezone.utc) - last_activity
            if elapsed > self._session_timeout:
                logger.debug(
                    "Chat session expired for user_id=%d (%.0f min ago)",
                    user_id,
                    elapsed.total_seconds() / 60,
                )
                await repos.clear_chat_session(session, user_id)
                await session.commit()
                return None

            return await repos.get_chat_response_id(session, user_id)

    async def save_response_id(self, user_id: int, response_id: str) -> None:
        """Persist latest response id and activity timestamp."""
        if not response_id:
            return
        async with self._session_factory() as session:
            await repos.update_chat_response_id(session, user_id, response_id)
            await session.commit()

    async def clear_session(self, user_id: int) -> None:
        """Clear chat session pointer for explicit reset or mode switches."""
        async with self._session_factory() as session:
            await repos.clear_chat_session(session, user_id)
            await session.commit()

    async def build_user_context(self, user_id: int) -> str:
        """Build durable context from memory + active goals + sprint progress."""
        parts: list[str] = []

        async with self._session_factory() as session:
            try:
                memory = await memory_service.get_context(
                    session,
                    user_id,
                    max_tokens=self._memory_context_max_tokens,
                )
                if memory:
                    parts.append(f"Недавняя история:\n{memory}")
            except Exception:
                logger.exception(
                    "Failed to load memory context for user_id=%d",
                    user_id,
                )

            try:
                goals = await repos.get_active_goals(session, user_id)
                if goals:
                    goal_lines = [f"- {goal.title}" for goal in goals]
                    parts.append("Активные цели:\n" + "\n".join(goal_lines))

                sprint = await repos.get_active_sprint(session, user_id)
                if sprint is not None:
                    week = repos.get_current_week_number(sprint)
                    days_left = repos.get_sprint_days_remaining(sprint)
                    parts.append(
                        "Прогресс спринта:\n"
                        f"- Текущая неделя: {week} из 12\n"
                        f"- Осталось дней: {days_left}"
                    )
            except Exception:
                logger.exception(
                    "Failed to load goals/sprint context for user_id=%d",
                    user_id,
                )

        return "\n\n".join(parts)

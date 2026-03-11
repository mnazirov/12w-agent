"""Async MCP client wrapper for motivation tracker tools."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from mcp import ClientSession
from mcp.client.sse import sse_client

logger = logging.getLogger(__name__)


class MCPMotivationClient:
    """Client for calling motivation-related MCP tools over SSE."""

    def __init__(self, server_url: str) -> None:
        self.server_url = server_url

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[ClientSession]:
        """Open MCP session using SSE transport."""
        async with sse_client(self.server_url) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                yield session

    async def _call(
        self,
        name: str,
        args: dict,
        session: ClientSession | None = None,
    ) -> dict:
        """Call an MCP tool and parse JSON payload from text content."""
        try:
            if session is not None:
                result = await session.call_tool(name, args)
            else:
                async with self._session() as sess:
                    result = await sess.call_tool(name, args)

            text = "{}"
            if getattr(result, "content", None):
                text = getattr(result.content[0], "text", "{}") or "{}"
            return json.loads(text)
        except Exception as exc:
            logger.exception("MCP tool call failed (%s): %s", name, exc)
            return {"error": str(exc)}

    async def log_activity(self, user_id: int, action: str, details: str = "") -> dict:
        return await self._call(
            "log_activity",
            {"user_id": user_id, "action": action, "details": details},
        )

    async def get_achievement_report(self, user_id: int, days: int = 7) -> dict:
        return await self._call(
            "get_achievement_report",
            {"user_id": user_id, "days": days},
        )

    async def check_engagement(self, user_id: int) -> dict:
        return await self._call("check_engagement", {"user_id": user_id})

    async def generate_motivation_context(self, user_id: int) -> dict:
        return await self._call("generate_motivation_context", {"user_id": user_id})

    async def get_motivation_config(self, user_id: int) -> dict:
        return await self._call("get_motivation_config", {"user_id": user_id})

    async def update_motivation_config(self, user_id: int, **kwargs: Any) -> dict:
        return await self._call("update_motivation_config", {"user_id": user_id, **kwargs})

    async def record_motivation_sent(
        self,
        user_id: int,
        message_type: str,
        engagement_level: str | None,
        message: str,
    ) -> dict:
        return await self._call(
            "record_motivation_sent",
            {
                "user_id": user_id,
                "message_type": message_type,
                "engagement_level": engagement_level,
                "message": message,
            },
        )

    async def get_users_needing_motivation(self) -> list[int]:
        data = await self._call("get_users_needing_motivation", {})
        users = data.get("users", []) if isinstance(data, dict) else []
        out: list[int] = []
        for user in users:
            try:
                out.append(int(user))
            except (TypeError, ValueError):
                continue
        return out

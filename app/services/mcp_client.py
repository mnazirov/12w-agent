"""Async MCP client wrapper for motivation tracker tools."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, AsyncIterator

from mcp import ClientSession
from mcp.client.sse import sse_client

logger = logging.getLogger(__name__)


class MCPMotivationClient:
    """Client for calling motivation-related MCP tools over SSE."""

    def __init__(
        self,
        server_url: str,
        *,
        persistent: bool = False,
        reconnect_attempts: int = 1,
    ) -> None:
        self.server_url = server_url
        self.persistent = persistent
        self.reconnect_attempts = max(0, reconnect_attempts)
        self._session_lock = asyncio.Lock()
        self._persistent_stack: AsyncExitStack | None = None
        self._persistent_session: ClientSession | None = None

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[ClientSession]:
        """Open MCP session using SSE transport."""
        async with sse_client(self.server_url) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                yield session

    @staticmethod
    def _parse_result(result: Any) -> Any:
        """Parse MCP tool result into a JSON-like dict."""
        structured = getattr(result, "structuredContent", None)
        if structured is not None:
            return structured

        text = "{}"
        content = getattr(result, "content", None)
        if content:
            first = content[0]
            text = getattr(first, "text", "{}") or "{}"
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"text": text}

    async def _ensure_connected_locked(self) -> ClientSession:
        """Create and initialize persistent session (lock must be held)."""
        if self._persistent_session is not None:
            return self._persistent_session

        stack = AsyncExitStack()
        try:
            streams = await stack.enter_async_context(sse_client(self.server_url))
            session = await stack.enter_async_context(ClientSession(*streams))
            await session.initialize()
        except Exception:
            await stack.aclose()
            raise

        self._persistent_stack = stack
        self._persistent_session = session
        return session

    async def _reset_connection_locked(self) -> None:
        """Close persistent session resources (lock must be held)."""
        if self._persistent_stack is not None:
            try:
                await self._persistent_stack.aclose()
            finally:
                self._persistent_stack = None
                self._persistent_session = None

    async def connect(self) -> None:
        """Open persistent SSE session if client is in persistent mode."""
        if not self.persistent:
            return
        async with self._session_lock:
            await self._ensure_connected_locked()

    async def disconnect(self) -> None:
        """Close persistent SSE session if opened."""
        async with self._session_lock:
            await self._reset_connection_locked()

    async def call_tool(self, name: str, args: dict[str, Any] | None = None) -> Any:
        """Call any MCP tool by name."""
        return await self._call(name=name, args=args or {})

    async def list_tools(self) -> list[dict[str, Any]]:
        """Discover MCP tools using tools/list."""
        try:
            if self.persistent:
                async with self._session_lock:
                    session = await self._ensure_connected_locked()
                    return await self._list_tools_from_session(session)

            async with self._session() as session:
                return await self._list_tools_from_session(session)
        except Exception as exc:
            logger.exception("MCP tools/list failed: %s", exc)
            return []

    async def _list_tools_from_session(self, session: ClientSession) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        cursor: str | None = None

        while True:
            result = await session.list_tools(cursor=cursor)
            for tool in getattr(result, "tools", []) or []:
                if hasattr(tool, "model_dump"):
                    tools.append(tool.model_dump(by_alias=True))
                elif isinstance(tool, dict):
                    tools.append(tool)
            cursor = getattr(result, "nextCursor", None)
            if not cursor:
                break

        return tools

    async def _call(
        self,
        name: str,
        args: dict,
        session: ClientSession | None = None,
    ) -> Any:
        """Call an MCP tool and parse JSON payload from text content."""
        try:
            if session is not None:
                result = await session.call_tool(name, args)
                return self._parse_result(result)

            if self.persistent:
                async with self._session_lock:
                    return await self._call_persistent_locked(name, args)

            else:
                async with self._session() as sess:
                    result = await sess.call_tool(name, args)
            return self._parse_result(result)
        except Exception as exc:
            logger.exception("MCP tool call failed (%s): %s", name, exc)
            return {"error": str(exc)}

    async def _call_persistent_locked(self, name: str, args: dict) -> Any:
        attempts = self.reconnect_attempts + 1
        last_exc: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                session = await self._ensure_connected_locked()
                result = await session.call_tool(name, args)
                return self._parse_result(result)
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "MCP persistent call failed (%s), attempt %d/%d: %s",
                    name,
                    attempt,
                    attempts,
                    exc,
                )
                await self._reset_connection_locked()

        message = str(last_exc) if last_exc else "Unknown MCP error"
        logger.error("MCP call failed after retries (%s): %s", name, message)
        return {"error": message}

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

    async def get_today_actions(self, user_id: int) -> dict:
        return await self._call("get_today_actions", {"user_id": user_id})

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

    async def collect_week_data(self, user_id: int, days: int = 7) -> dict:
        return await self._call(
            "collect_week_data", {"user_id": user_id, "days": days}
        )

    async def analyze_patterns(self, raw_data_json: str) -> dict:
        return await self._call(
            "analyze_patterns", {"raw_data_json": raw_data_json}
        )

    async def save_weekly_report(self, user_id: int, report_json: str) -> dict:
        return await self._call(
            "save_weekly_report",
            {"user_id": user_id, "report_json": report_json},
        )

    async def get_previous_reports(self, user_id: int, limit: int = 4) -> dict:
        return await self._call(
            "get_previous_reports", {"user_id": user_id, "limit": limit}
        )

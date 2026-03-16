"""Tests for MCPOrchestrator multi-server routing and discovery."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.services.mcp_orchestrator import MCPOrchestrator


class _FakeMCPClient:
    def __init__(
        self,
        *,
        tools: list[dict] | None = None,
        connect_error: Exception | None = None,
        call_result: dict | None = None,
    ) -> None:
        self._connect_error = connect_error
        self.connect = AsyncMock(side_effect=self._connect)
        self.disconnect = AsyncMock()
        self.list_tools = AsyncMock(return_value=tools or [])
        self.call_tool = AsyncMock(return_value=call_result or {"status": "ok"})

    async def _connect(self) -> None:
        if self._connect_error is not None:
            raise self._connect_error


class _FakeGoogleAuth:
    def __init__(self, token: str | None = "mock-token") -> None:
        self.get_valid_access_token = AsyncMock(return_value=token)


@pytest.mark.asyncio
async def test_register_server_adds_client_to_registry() -> None:
    client = _FakeMCPClient()
    orchestrator = MCPOrchestrator(client_factory=lambda _: client)

    await orchestrator.register_server("motivation", "http://mcp:8001/sse", "Motivation")

    assert orchestrator.get_server_client("motivation") is client


@pytest.mark.asyncio
async def test_collision_detection_applies_server_prefix() -> None:
    motivation = _FakeMCPClient(
        tools=[
            {
                "name": "list_events",
                "description": "Motivation events",
                "inputSchema": {"type": "object", "properties": {}},
            }
        ]
    )
    calendar = _FakeMCPClient(
        tools=[
            {
                "name": "list_events",
                "description": "Calendar events",
                "inputSchema": {"type": "object", "properties": {}},
            }
        ]
    )
    clients = {
        "http://motivation/sse": motivation,
        "http://calendar/sse": calendar,
    }
    orchestrator = MCPOrchestrator(client_factory=lambda url: clients[url])
    await orchestrator.register_server("motivation", "http://motivation/sse", "Motivation")
    await orchestrator.register_server("calendar", "http://calendar/sse", "Calendar")

    await orchestrator.connect_all()
    names = {tool["name"] for tool in orchestrator.get_tools_for_openai()}

    assert "list_events" in names
    assert "calendar_list_events" in names


@pytest.mark.asyncio
async def test_routes_tool_call_to_matching_server() -> None:
    motivation = _FakeMCPClient(
        tools=[
            {
                "name": "get_achievement_report",
                "description": "Achievements",
                "inputSchema": {"type": "object", "properties": {"user_id": {"type": "integer"}}},
            }
        ]
    )
    calendar = _FakeMCPClient(
        tools=[
            {
                "name": "list_events",
                "description": "Calendar list",
                "inputSchema": {"type": "object", "properties": {"calendar_id": {"type": "string"}}},
            }
        ],
        call_result={"events": []},
    )
    clients = {
        "http://motivation/sse": motivation,
        "http://calendar/sse": calendar,
    }
    orchestrator = MCPOrchestrator(
        client_factory=lambda url: clients[url],
        google_auth_service=_FakeGoogleAuth(),
    )
    await orchestrator.register_server("motivation", "http://motivation/sse", "Motivation")
    await orchestrator.register_server("calendar", "http://calendar/sse", "Calendar")
    await orchestrator.connect_all()

    result = await orchestrator.call_tool(
        "list_events",
        {"calendar_id": "primary"},
        user_id=777,
    )

    assert result == {"events": []}
    calendar.call_tool.assert_awaited_once_with(
        "list_events",
        {"calendar_id": "primary", "access_token": "mock-token"},
    )
    motivation.call_tool.assert_not_called()


@pytest.mark.asyncio
async def test_graceful_degradation_when_server_unavailable() -> None:
    motivation = _FakeMCPClient(
        tools=[
            {
                "name": "get_achievement_report",
                "description": "Achievements",
                "inputSchema": {"type": "object", "properties": {}},
            }
        ]
    )
    calendar = _FakeMCPClient(connect_error=RuntimeError("calendar down"))
    clients = {
        "http://motivation/sse": motivation,
        "http://calendar/sse": calendar,
    }
    orchestrator = MCPOrchestrator(client_factory=lambda url: clients[url])
    await orchestrator.register_server("motivation", "http://motivation/sse", "Motivation")
    await orchestrator.register_server("calendar", "http://calendar/sse", "Calendar")

    await orchestrator.connect_all()
    tools = orchestrator.get_tools_for_openai()

    assert len(tools) == 1
    assert tools[0]["name"] == "get_achievement_report"


@pytest.mark.asyncio
async def test_get_tools_for_openai_returns_function_schema() -> None:
    motivation = _FakeMCPClient(
        tools=[
            {
                "name": "collect_week_data",
                "description": "Collect stats",
                "inputSchema": {
                    "type": "object",
                    "properties": {"user_id": {"type": "integer"}},
                    "required": ["user_id"],
                },
            }
        ]
    )
    orchestrator = MCPOrchestrator(client_factory=lambda _: motivation)
    await orchestrator.register_server("motivation", "http://motivation/sse", "Motivation")
    await orchestrator.connect_all()

    tools = orchestrator.get_tools_for_openai()

    assert tools == [
        {
            "type": "function",
            "name": "collect_week_data",
            "description": "Collect stats",
            "parameters": {
                "type": "object",
                "properties": {"user_id": {"type": "integer"}},
                "required": ["user_id"],
            },
        }
    ]


@pytest.mark.asyncio
async def test_call_tool_on_server_for_backward_compatibility() -> None:
    motivation = _FakeMCPClient(call_result={"status": "ok"})
    orchestrator = MCPOrchestrator(client_factory=lambda _: motivation)
    await orchestrator.register_server("motivation", "http://motivation/sse", "Motivation")
    await orchestrator.connect_all()

    result = await orchestrator.call_tool_on_server(
        "motivation",
        "log_activity",
        {"user_id": 1, "action": "plan"},
    )

    assert result == {"status": "ok"}
    motivation.call_tool.assert_awaited_once_with(
        "log_activity",
        {"user_id": 1, "action": "plan"},
    )

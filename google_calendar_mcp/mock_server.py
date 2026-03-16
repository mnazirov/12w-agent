"""Mock Google Calendar MCP server for local integration testing."""

from __future__ import annotations

import json
import os

from mcp.server.fastmcp import FastMCP

MCP_HOST = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.getenv("MCP_PORT", "8002"))

mcp = FastMCP(
    "google-calendar-mock",
    instructions="Mock Google Calendar tools for development and testing.",
    host=MCP_HOST,
    port=MCP_PORT,
)


@mcp.tool()
def list_calendars() -> str:
    """Return available calendars."""
    return json.dumps([{"id": "primary", "summary": "My Calendar"}])


def _auth_error() -> str:
    return json.dumps(
        {
            "error": "Not authenticated. Use /connect_google in Telegram.",
            "requires_auth": True,
        }
    )


@mcp.tool()
def list_events(
    calendar_id: str = "primary",
    time_min: str | None = None,
    time_max: str | None = None,
    access_token: str = "",
) -> str:
    """Return events in the given interval (mock always returns empty list)."""
    if not access_token:
        return _auth_error()
    _ = (calendar_id, time_min, time_max)
    return json.dumps({"events": [], "calendar_id": calendar_id})


@mcp.tool()
def create_event(
    summary: str,
    start: str,
    end: str,
    calendar_id: str = "primary",
    access_token: str = "",
) -> str:
    """Create event in calendar (mock response)."""
    if not access_token:
        return _auth_error()
    _ = (summary, start, end, calendar_id)
    return json.dumps({"status": "created", "id": "mock-123"})


@mcp.tool()
def delete_event(
    event_id: str,
    calendar_id: str = "primary",
    access_token: str = "",
) -> str:
    """Delete event from calendar (mock response)."""
    if not access_token:
        return _auth_error()
    _ = (event_id, calendar_id)
    return json.dumps({"status": "deleted"})

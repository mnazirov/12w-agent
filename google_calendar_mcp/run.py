"""Entry point for the mock Google Calendar MCP server."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from mock_server import mcp  # noqa: E402

if __name__ == "__main__":
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8002"))

    if hasattr(mcp, "settings"):
        try:
            mcp.settings.host = host
            mcp.settings.port = port
        except Exception:
            pass

    try:
        mcp.run(transport="sse", host=host, port=port)
    except TypeError:
        mcp.run(transport="sse")

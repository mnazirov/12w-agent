"""Entry point for the MCP motivation server (SSE transport)."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from server import mcp  # noqa: E402

if __name__ == "__main__":
    port = int(os.getenv("MCP_PORT", "8001"))
    mcp.run(transport="sse", host="0.0.0.0", port=port)

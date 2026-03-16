"""MCP orchestration layer with multi-server discovery and tool routing."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from app.services.mcp_client import MCPMotivationClient

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.services.google_auth_service import GoogleAuthService


@dataclass
class _ToolRoute:
    server_name: str
    original_name: str
    openai_name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class _ServerState:
    name: str
    url: str
    description: str
    client: MCPMotivationClient
    available: bool = False
    last_error: str | None = None
    tools: dict[str, dict[str, Any]] = field(default_factory=dict)


class MCPOrchestrator:
    """Aggregate multiple MCP servers behind a unified tool interface."""

    def __init__(
        self,
        client_factory: Callable[[str], MCPMotivationClient] | None = None,
        google_auth_service: GoogleAuthService | None = None,
    ) -> None:
        if client_factory is None:
            client_factory = lambda url: MCPMotivationClient(
                url,
                persistent=True,
                reconnect_attempts=1,
            )
        self._client_factory = client_factory
        self._google_auth_service = google_auth_service
        self._servers: dict[str, _ServerState] = {}
        self._routes: dict[str, _ToolRoute] = {}
        self._openai_tools: list[dict[str, Any]] = []

    def set_google_auth_service(self, service: GoogleAuthService | None) -> None:
        """Attach Google auth service for calendar token injection."""
        self._google_auth_service = service

    async def register_server(self, name: str, url: str, description: str) -> None:
        """Register an MCP server descriptor and prepare a dedicated client."""
        if not name:
            raise ValueError("server name cannot be empty")
        client = self._client_factory(url)
        self._servers[name] = _ServerState(
            name=name,
            url=url,
            description=description,
            client=client,
        )

    async def connect_all(self) -> None:
        """Connect all registered servers and build tool registry."""
        self._routes = {}
        self._openai_tools = []

        # Preserves registration order for deterministic collision handling.
        for state in self._servers.values():
            state.available = False
            state.last_error = None
            state.tools = {}

            try:
                await state.client.connect()
                tools = await state.client.list_tools()
                state.tools = {
                    str(tool.get("name")): tool
                    for tool in tools
                    if isinstance(tool, dict) and tool.get("name")
                }
                state.available = True
                logger.info(
                    "MCP server '%s' connected (%d tool(s))",
                    state.name,
                    len(state.tools),
                )
            except Exception as exc:
                state.available = False
                state.last_error = str(exc)
                logger.warning(
                    "MCP server '%s' unavailable at startup (%s): %s",
                    state.name,
                    state.url,
                    exc,
                )

        self._rebuild_routes()

    async def disconnect_all(self) -> None:
        """Disconnect all server clients independently."""
        for state in self._servers.values():
            try:
                await state.client.disconnect()
            except Exception as exc:
                logger.warning("MCP server '%s' disconnect failed: %s", state.name, exc)

    def get_server_client(self, name: str) -> MCPMotivationClient | None:
        """Return dedicated MCP client for the given server."""
        state = self._servers.get(name)
        return state.client if state else None

    @property
    def motivation(self) -> MCPMotivationClient | None:
        """Convenience accessor for backward-compatible motivation client usage."""
        return self.get_server_client("motivation")

    def _rebuild_routes(self) -> None:
        used_names: set[str] = set()
        routes: dict[str, _ToolRoute] = {}
        openai_tools: list[dict[str, Any]] = []

        for state in self._servers.values():
            if not state.available:
                continue

            for original_name, tool in state.tools.items():
                base_name = original_name
                openai_name = base_name
                if openai_name in used_names:
                    openai_name = f"{state.name}_{base_name}"
                    suffix = 2
                    while openai_name in used_names:
                        openai_name = f"{state.name}_{base_name}_{suffix}"
                        suffix += 1
                    logger.warning(
                        "MCP tool name collision for '%s'; exposed as '%s'",
                        base_name,
                        openai_name,
                    )

                used_names.add(openai_name)
                schema = tool.get("inputSchema")
                if not isinstance(schema, dict):
                    schema = {"type": "object", "properties": {}}
                description = str(
                    tool.get("description")
                    or f"{state.description}. Tool: {original_name}"
                )

                route = _ToolRoute(
                    server_name=state.name,
                    original_name=original_name,
                    openai_name=openai_name,
                    description=description,
                    input_schema=schema,
                )
                routes[openai_name] = route
                openai_tools.append(
                    {
                        "type": "function",
                        "name": openai_name,
                        "description": description,
                        "parameters": schema,
                    }
                )

        self._routes = routes
        self._openai_tools = openai_tools

    def get_tools_for_openai(self, server_names: list[str] | set[str] | None = None) -> list[dict]:
        """Return discovered tools in OpenAI Responses API format."""
        if not server_names:
            return list(self._openai_tools)

        allowed = set(server_names)
        return [
            tool
            for tool in self._openai_tools
            if self._routes.get(str(tool.get("name"))) is not None
            and self._routes[str(tool["name"])].server_name in allowed
        ]

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        user_id: int | None = None,
    ) -> Any:
        """Route tool call by OpenAI-visible name and execute on matching server."""
        route = self._routes.get(tool_name)
        if route is None:
            return {
                "error": f"Unknown MCP tool: {tool_name}",
                "error_type": "tool_not_found",
                "tool_name": tool_name,
            }
        return await self.call_tool_on_server(
            server_name=route.server_name,
            tool_name=route.original_name,
            arguments=arguments,
            user_id=user_id,
        )

    async def call_tool_on_server(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        user_id: int | None = None,
    ) -> Any:
        """Call a tool explicitly on selected server (backward compatibility path)."""
        state = self._servers.get(server_name)
        if state is None:
            return {
                "error": f"Unknown MCP server: {server_name}",
                "error_type": "server_not_found",
                "server_name": server_name,
                "tool_name": tool_name,
            }

        if not state.available:
            # Best-effort lazy reconnect for long-running bot process.
            try:
                await state.client.connect()
                state.available = True
            except Exception as exc:
                state.last_error = str(exc)
                return {
                    "error": f"MCP server '{server_name}' is unavailable",
                    "error_type": "server_unavailable",
                    "server_name": server_name,
                    "tool_name": tool_name,
                    "details": str(exc),
                }

        call_arguments = dict(arguments or {})
        if server_name == "calendar":
            auth_result = await self._inject_calendar_auth(call_arguments, user_id)
            if auth_result is not None:
                return auth_result

        try:
            result = await state.client.call_tool(tool_name, call_arguments)
            if isinstance(result, dict) and result.get("error"):
                # Preserve error contract but add routing metadata.
                result.setdefault("server_name", server_name)
                result.setdefault("tool_name", tool_name)
            return result
        except Exception as exc:
            state.available = False
            state.last_error = str(exc)
            logger.exception(
                "MCP routed tool call failed (%s::%s): %s",
                server_name,
                tool_name,
                exc,
            )
            return {
                "error": f"Tool call failed: {exc}",
                "error_type": "tool_call_failed",
                "server_name": server_name,
                "tool_name": tool_name,
            }

    async def _inject_calendar_auth(
        self,
        arguments: dict[str, Any],
        user_id: int | None,
    ) -> dict[str, Any] | None:
        """Inject per-user access token for calendar tools."""
        if user_id is None:
            return {
                "error": "Google-аккаунт не подключён. Используйте /connect_google",
                "requires_auth": True,
            }
        if self._google_auth_service is None:
            return {
                "error": "Google OAuth не настроен администратором.",
                "requires_auth": True,
            }

        token = await self._google_auth_service.get_valid_access_token(user_id)
        if not token:
            return {
                "error": (
                    "Google-аккаунт не подключён или сессия истекла. "
                    "Используйте /connect_google"
                ),
                "requires_auth": True,
            }

        arguments["access_token"] = token
        return None

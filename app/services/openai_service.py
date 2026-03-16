"""OpenAI API wrapper with template loading, JSON validation, and guardrails."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Type, TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.config import OPENAI_API_KEY, OPENAI_MAX_TOKENS, OPENAI_MODEL, OPENAI_TIMEOUT

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None

# Prompt template directory
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

T = TypeVar("T", bound=BaseModel)

if TYPE_CHECKING:
    from app.services.mcp_orchestrator import MCPOrchestrator


def _calendar_auth_required_message() -> str:
    return (
        "Google-аккаунт не подключён или сессия истекла. "
        "Используйте /connect_google"
    )


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=OPENAI_API_KEY, timeout=OPENAI_TIMEOUT)
    return _client


def load_template(name: str) -> str:
    """Load a .md prompt template by name (without extension)."""
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8")


def render_template(name: str, **variables: Any) -> str:
    """Load template and substitute {variables}."""
    tpl = load_template(name)
    for key, value in variables.items():
        tpl = tpl.replace(f"{{{key}}}", str(value) if value is not None else "—")
    return tpl


def build_system_prompt(user_context: str) -> str:
    """Build the base system instruction with user context injected."""
    return render_template("system", user_context=user_context)


def _compose_chat_instructions(system_prompt: str, user_context: str = "") -> str:
    """Merge base chat instructions with dynamic user context."""
    instructions = system_prompt.strip()
    if "{user_context}" in instructions:
        return instructions.replace(
            "{user_context}",
            user_context or "Нет дополнительного контекста.",
        )

    if user_context:
        return f"{instructions}\n\n## Контекст пользователя\n{user_context}"
    return instructions


def _extract_json(text: str) -> str:
    """Try to extract JSON from model output that may contain markdown fences."""
    text = text.strip()
    # Strip markdown ```json ... ``` fences
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        start = 1
        end = len(lines)
        for i in range(len(lines) - 1, 0, -1):
            if lines[i].strip() == "```":
                end = i
                break
        text = "\n".join(lines[start:end]).strip()
    return text


def _obj_get(obj: Any, key: str, default: Any = None) -> Any:
    """Read key from dict-like or object-like SDK entities."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _parse_tool_arguments(arguments: Any) -> dict[str, Any]:
    """Normalize tool call arguments to a JSON object."""
    if arguments is None:
        return {}
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        raw = arguments.strip()
        if not raw:
            return {}
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse tool arguments JSON: %r", raw[:200])
            return {}
        if isinstance(decoded, dict):
            return decoded
        return {"value": decoded}
    return {}


@dataclass
class _FunctionCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class _ToolAuthRequiredInterrupt:
    output_text: str
    requires_auth: bool = True
    response_id: str | None = None


def _extract_function_calls(response: Any) -> list[_FunctionCall]:
    """Extract function/tool calls from a Responses API result."""
    calls: list[_FunctionCall] = []
    output_items = _obj_get(response, "output", []) or []

    for item in output_items:
        item_type = str(_obj_get(item, "type", ""))

        if item_type == "function_call":
            call_id = str(_obj_get(item, "call_id") or _obj_get(item, "id") or "")
            name = str(_obj_get(item, "name") or "")
            args = _parse_tool_arguments(_obj_get(item, "arguments"))
            if call_id and name:
                calls.append(_FunctionCall(call_id=call_id, name=name, arguments=args))
            continue

        # Compatibility fallback for SDK variants with nested function payload.
        if item_type == "tool_call":
            function_payload = _obj_get(item, "function", {})
            call_id = str(_obj_get(item, "call_id") or _obj_get(item, "id") or "")
            name = str(
                _obj_get(function_payload, "name")
                or _obj_get(item, "name")
                or ""
            )
            arguments = _obj_get(function_payload, "arguments")
            if arguments is None:
                arguments = _obj_get(item, "arguments")
            if call_id and name:
                calls.append(
                    _FunctionCall(
                        call_id=call_id,
                        name=name,
                        arguments=_parse_tool_arguments(arguments),
                    )
                )

    return calls


def _tool_output_to_string(result: Any) -> str:
    """Serialize tool output for function_call_output payload."""
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, ensure_ascii=False)
    except TypeError:
        return json.dumps({"result": str(result)}, ensure_ascii=False)


def _extract_requires_auth_message(result: Any) -> str | None:
    """Detect auth-required tool result across dict/string payload variants."""
    default_message = _calendar_auth_required_message()

    if isinstance(result, dict):
        if result.get("requires_auth"):
            message = str(result.get("error", "")).strip()
            return message or default_message

        text_payload = result.get("text")
        if isinstance(text_payload, str):
            nested = _extract_requires_auth_message(text_payload)
            if nested:
                return nested
        return None

    if isinstance(result, str):
        raw = result.strip()
        if not raw:
            return None
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            lower = raw.lower()
            if "requires_auth" in lower and "true" in lower:
                return default_message
            return None
        return _extract_requires_auth_message(decoded)

    return None


def _sanitize_auth_noise(text: str) -> str:
    """Collapse noisy auth loops into a single user-facing instruction."""
    if not text:
        return ""
    lowered = text.lower()
    if re.search(r'"requires_auth"\s*:\s*true', lowered):
        return _calendar_auth_required_message()
    if lowered.count("requires_auth") >= 2:
        return _calendar_auth_required_message()
    if "/list_calendars" in lowered and "requires_auth" in lowered:
        return _calendar_auth_required_message()
    return text


_KNOWN_TRACE_TOOLS = {
    "list_calendars",
    "list_events",
    "create_event",
    "delete_event",
}


def _is_trace_tool_name(name: str) -> bool:
    """Return True for known MCP tool names that may leak into output."""
    if name in _KNOWN_TRACE_TOOLS:
        return True
    return any(name.endswith(f"_{tool}") for tool in _KNOWN_TRACE_TOOLS)


def _strip_tool_trace_artifacts(text: str) -> str:
    """Remove leaked tool-call trace fragments like /tool_name{...}."""
    if not text:
        return ""

    out: list[str] = []
    i = 0
    removed_blocks = 0
    length = len(text)

    while i < length:
        if text[i] == "/":
            j = i + 1
            if j < length and (text[j].isalpha() or text[j] == "_"):
                while j < length and (text[j].isalnum() or text[j] == "_"):
                    j += 1
                tool_name = text[i + 1:j]
                if j < length and text[j] == "{" and _is_trace_tool_name(tool_name):
                    depth = 0
                    k = j
                    while k < length:
                        ch = text[k]
                        if ch == "{":
                            depth += 1
                        elif ch == "}":
                            depth -= 1
                            if depth == 0:
                                k += 1
                                break
                        k += 1
                    if depth == 0:
                        removed_blocks += 1
                        i = k
                        # Trim delimiters around removed tool fragments.
                        while i < length and text[i] in " \t\r\n|,;:/_-":
                            i += 1
                        continue

        out.append(text[i])
        i += 1

    if removed_blocks == 0:
        return text

    cleaned = "".join(out)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    # Heuristic for leaked glue text like "нахГотово" between stripped traces.
    if removed_blocks >= 2:
        start = re.search(r"[A-ZА-ЯЁ]", cleaned)
        if start and start.start() > 0:
            prefix = cleaned[:start.start()]
            if (
                len(prefix) <= 20
                and not any(ch.isspace() for ch in prefix)
                and not any(ch.isupper() for ch in prefix)
                and not any(ch.isdigit() for ch in prefix)
            ):
                cleaned = cleaned[start.start():].lstrip()

    return cleaned


async def _create_response_with_optional_tools(
    *,
    model: str,
    instructions: str | None,
    input_payload: Any,
    max_output_tokens: int,
    mcp_orchestrator: MCPOrchestrator | None = None,
    use_tools: bool = False,
    tool_server_names: list[str] | None = None,
    user_id: int | None = None,
    previous_response_id: str | None = None,
    max_tool_rounds: int = 6,
) -> Any | _ToolAuthRequiredInterrupt:
    """Create a Responses API completion and optionally resolve MCP tool calls."""
    client = get_client()

    tools: list[dict[str, Any]] = []
    if use_tools and mcp_orchestrator is not None:
        tools = mcp_orchestrator.get_tools_for_openai(server_names=tool_server_names)

    request: dict[str, Any] = {
        "model": model,
        "instructions": instructions or None,
        "input": input_payload,
        "max_output_tokens": max_output_tokens,
    }
    if tools:
        request["tools"] = tools
    if previous_response_id:
        request["previous_response_id"] = previous_response_id

    response = await client.responses.create(**request)
    if not tools or mcp_orchestrator is None:
        return response

    for _ in range(max_tool_rounds):
        calls = _extract_function_calls(response)
        if not calls:
            return response

        tool_outputs: list[dict[str, Any]] = []
        for call in calls:
            tool_result = await mcp_orchestrator.call_tool(
                call.name,
                call.arguments,
                user_id=user_id,
            )
            auth_message = _extract_requires_auth_message(tool_result)
            if auth_message:
                return _ToolAuthRequiredInterrupt(
                    output_text=auth_message,
                )
            tool_outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": _tool_output_to_string(tool_result),
                }
            )

        followup: dict[str, Any] = {
            "model": model,
            "instructions": instructions or None,
            "input": tool_outputs,
            "max_output_tokens": max_output_tokens,
            "tools": tools,
        }
        response_id = _obj_get(response, "id")
        if response_id:
            followup["previous_response_id"] = response_id

        response = await client.responses.create(**followup)

    logger.warning("Tool-call loop limit reached (%d rounds)", max_tool_rounds)
    return response


async def call_structured(
    template_name: str,
    variables: dict[str, Any],
    response_model: Type[T],
    system_context: str = "",
    max_retries: int = 2,
    mcp_orchestrator: MCPOrchestrator | None = None,
    use_tools: bool = False,
    tool_server_names: list[str] | None = None,
    user_id: int | None = None,
) -> T:
    """Call OpenAI with a template, parse and validate JSON response via Pydantic.

    Raises ValueError if validation fails after retries.
    """
    user_prompt = render_template(template_name, **variables)
    system_prompt = build_system_prompt(system_context) if system_context else ""

    last_error: Exception | None = None
    raw = ""
    for attempt in range(max_retries + 1):
        try:
            response = await _create_response_with_optional_tools(
                model=OPENAI_MODEL,
                instructions=system_prompt,
                input_payload=user_prompt,
                max_output_tokens=OPENAI_MAX_TOKENS,
                mcp_orchestrator=mcp_orchestrator,
                use_tools=use_tools,
                tool_server_names=tool_server_names,
                user_id=user_id,
            )
            if isinstance(response, _ToolAuthRequiredInterrupt):
                # For structured tasks (e.g. planning) gracefully fallback without tools.
                response = await _create_response_with_optional_tools(
                    model=OPENAI_MODEL,
                    instructions=system_prompt,
                    input_payload=user_prompt,
                    max_output_tokens=OPENAI_MAX_TOKENS,
                    mcp_orchestrator=mcp_orchestrator,
                    use_tools=False,
                    tool_server_names=tool_server_names,
                    user_id=user_id,
                )
            raw = response.output_text or ""
            cleaned = _extract_json(raw)
            data = json.loads(cleaned)
            return response_model.model_validate(data)
        except json.JSONDecodeError as e:
            last_error = e
            logger.warning(
                "JSON parse error (attempt %d/%d) for template '%s': %s. Raw: %s",
                attempt + 1, max_retries + 1, template_name, e, raw[:200],
            )
        except ValidationError as e:
            last_error = e
            logger.warning(
                "Pydantic validation error (attempt %d/%d) for template '%s': %s",
                attempt + 1, max_retries + 1, template_name, e,
            )
        except Exception as e:
            last_error = e
            logger.exception(
                "OpenAI call failed (attempt %d/%d) for template '%s': %s",
                attempt + 1, max_retries + 1, template_name, e,
            )
            if attempt == max_retries:
                break

    raise ValueError(
        f"Failed to get valid structured response for '{template_name}' "
        f"after {max_retries + 1} attempts: {last_error}"
    )


async def generate_chat(
    user_message: str,
    system_prompt: str,
    user_context: str = "",
    previous_response_id: str | None = None,
    mcp_orchestrator: MCPOrchestrator | None = None,
    use_tools: bool = False,
    tool_server_names: list[str] | None = None,
    user_id: int | None = None,
    max_output_tokens: int = OPENAI_MAX_TOKENS,
) -> tuple[str, str | None]:
    """Multi-turn free chat via Responses API."""
    instructions = _compose_chat_instructions(system_prompt, user_context)

    response = await _create_response_with_optional_tools(
        model=OPENAI_MODEL,
        instructions=instructions,
        input_payload=user_message,
        max_output_tokens=max_output_tokens,
        mcp_orchestrator=mcp_orchestrator,
        use_tools=use_tools,
        tool_server_names=tool_server_names,
        user_id=user_id,
        previous_response_id=previous_response_id,
    )
    if isinstance(response, _ToolAuthRequiredInterrupt):
        return response.output_text, None

    raw_text = (response.output_text or "").strip()

    text = _sanitize_auth_noise(raw_text)
    if text != raw_text:
        return text, None

    text = _strip_tool_trace_artifacts(text)
    if text != raw_text:
        return text, None

    return text, _obj_get(response, "id")


async def call_text(
    user_message: str,
    system_context: str = "",
    goals: list[str] | None = None,
    first_name: str | None = None,
    mcp_orchestrator: MCPOrchestrator | None = None,
    use_tools: bool = False,
    tool_server_names: list[str] | None = None,
    user_id: int | None = None,
) -> str:
    """Free-form text chat with the AI coach."""
    # Build context parts
    parts: list[str] = []
    if first_name:
        parts.append(f"User's name: {first_name}")
    if goals:
        goals_str = "\n".join(f"- {g}" for g in goals)
        parts.append(f"12-week goals:\n{goals_str}")
    context = "\n".join(parts) if parts else "No additional context."

    system_prompt = build_system_prompt(context)
    if system_context:
        system_prompt = f"{system_prompt}\n\nAdditional instructions:\n{system_context}"

    try:
        response = await _create_response_with_optional_tools(
            model=OPENAI_MODEL,
            instructions=system_prompt,
            input_payload=user_message,
            max_output_tokens=OPENAI_MAX_TOKENS,
            mcp_orchestrator=mcp_orchestrator,
            use_tools=use_tools,
            tool_server_names=tool_server_names,
            user_id=user_id,
        )
        if isinstance(response, _ToolAuthRequiredInterrupt):
            return response.output_text
        return response.output_text or ""
    except Exception as e:
        logger.exception("OpenAI text call failed: %s", e)
        raise

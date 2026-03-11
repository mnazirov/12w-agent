"""OpenAI API wrapper with template loading, JSON validation, and guardrails."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Type, TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.config import OPENAI_API_KEY, OPENAI_MAX_TOKENS, OPENAI_MODEL, OPENAI_TIMEOUT

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None

# Prompt template directory
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

T = TypeVar("T", bound=BaseModel)


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


async def call_structured(
    template_name: str,
    variables: dict[str, Any],
    response_model: Type[T],
    system_context: str = "",
    max_retries: int = 2,
) -> T:
    """Call OpenAI with a template, parse and validate JSON response via Pydantic.

    Raises ValueError if validation fails after retries.
    """
    client = get_client()
    user_prompt = render_template(template_name, **variables)
    system_prompt = build_system_prompt(system_context) if system_context else ""

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = await client.responses.create(
                model=OPENAI_MODEL,
                instructions=system_prompt or None,
                input=user_prompt,
                max_output_tokens=OPENAI_MAX_TOKENS,
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


async def call_text(
    user_message: str,
    system_context: str = "",
    goals: list[str] | None = None,
    first_name: str | None = None,
) -> str:
    """Free-form text chat with the AI coach."""
    client = get_client()

    # Build context parts
    parts: list[str] = []
    if first_name:
        parts.append(f"User's name: {first_name}")
    if goals:
        goals_str = "\n".join(f"- {g}" for g in goals)
        parts.append(f"12-week goals:\n{goals_str}")
    context = "\n".join(parts) if parts else "No additional context."

    system_prompt = build_system_prompt(context)

    try:
        response = await client.responses.create(
            model=OPENAI_MODEL,
            instructions=system_prompt,
            input=user_message,
            max_output_tokens=OPENAI_MAX_TOKENS,
        )
        return response.output_text or ""
    except Exception as e:
        logger.exception("OpenAI text call failed: %s", e)
        raise

"""Tests for chat output cleanup helpers in OpenAI service."""
from __future__ import annotations

from app.services.openai_service import (
    _extract_requires_auth_message,
    _strip_tool_trace_artifacts,
)


def test_strip_tool_trace_artifacts_removes_single_fragment() -> None:
    text = '/list_calendars{"calendars":[{"id":"primary"}]} Готово, календари получены.'
    cleaned = _strip_tool_trace_artifacts(text)
    assert cleaned == "Готово, календари получены."


def test_strip_tool_trace_artifacts_removes_multiple_fragments_and_prefix_noise() -> None:
    text = (
        '/list_calendars{"calendars":[{"id":"primary"}]} '
        'ಘ/create_event{"calendar_id":"primary","title":"A"} '
        'нах/create_event{"calendar_id":"primary","title":"B"} '
        "нахГотово, занёс в календарь."
    )
    cleaned = _strip_tool_trace_artifacts(text)
    assert cleaned == "Готово, занёс в календарь."


def test_strip_tool_trace_artifacts_keeps_normal_text_unchanged() -> None:
    text = "Готово, добавил два события и поставил напоминания."
    cleaned = _strip_tool_trace_artifacts(text)
    assert cleaned == text


def test_strip_tool_trace_artifacts_does_not_remove_unknown_slash_json() -> None:
    text = 'Пример пути /docs{v1} и обычный ответ.'
    cleaned = _strip_tool_trace_artifacts(text)
    assert cleaned == text


def test_strip_tool_trace_artifacts_removes_prefixed_known_tool_name() -> None:
    text = '/calendar_create_event{"calendar_id":"primary"} Сделано.'
    cleaned = _strip_tool_trace_artifacts(text)
    assert cleaned == "Сделано."


def test_extract_requires_auth_message_from_nested_text_payload() -> None:
    result = {
        "text": '{"error":"Not authenticated","requires_auth":true}'
    }
    message = _extract_requires_auth_message(result)
    assert message == "Not authenticated"

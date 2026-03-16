"""Tests for Google Calendar MCP tool handlers."""

from __future__ import annotations

import json

from google_calendar_mcp import mock_server


def _loads(raw: str) -> dict:
    return json.loads(raw)


def test_list_calendars_requires_auth_without_token() -> None:
    payload = _loads(mock_server.list_calendars())
    assert payload["requires_auth"] is True
    assert "connect_google" in payload["error"]


def test_list_calendars_maps_google_payload(monkeypatch) -> None:
    def fake_call_google_api(**_: object) -> tuple[int, dict]:
        return (
            200,
            {
                "items": [
                    {
                        "id": "primary",
                        "summary": "Личный",
                        "primary": True,
                        "accessRole": "owner",
                    }
                ]
            },
        )

    monkeypatch.setattr(mock_server, "_call_google_api", fake_call_google_api)

    payload = _loads(mock_server.list_calendars(access_token="token"))
    assert payload == {
        "calendars": [
            {
                "id": "primary",
                "summary": "Личный",
                "primary": True,
                "accessRole": "owner",
            }
        ]
    }


def test_create_event_accepts_title_alias(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_call_google_api(**kwargs: object) -> tuple[int, dict]:
        captured.update(kwargs)
        return (
            200,
            {
                "id": "evt-1",
                "summary": "Тестовое событие",
                "start": {"dateTime": "2026-03-16T14:20:00+02:00"},
                "end": {"dateTime": "2026-03-16T14:35:00+02:00"},
                "htmlLink": "https://calendar.google.com/event?eid=evt-1",
            },
        )

    monkeypatch.setattr(mock_server, "_call_google_api", fake_call_google_api)

    payload = _loads(
        mock_server.create_event(
            title="Тестовое событие",
            start="2026-03-16T14:20:00+02:00",
            end="2026-03-16T14:35:00+02:00",
            access_token="token",
        )
    )

    assert captured["method"] == "POST"
    assert captured["path"] == "/calendars/primary/events"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["summary"] == "Тестовое событие"
    assert payload["status"] == "created"
    assert payload["id"] == "evt-1"


def test_list_calendars_returns_error_payload_on_upstream_failure(monkeypatch) -> None:
    def fake_call_google_api(**_: object) -> tuple[int, dict]:
        return 500, {"error": {"message": "backend error"}}

    monkeypatch.setattr(mock_server, "_call_google_api", fake_call_google_api)

    payload = _loads(mock_server.list_calendars(access_token="token"))
    assert payload["error"] == "Google Calendar API request failed"
    assert payload["status_code"] == 500

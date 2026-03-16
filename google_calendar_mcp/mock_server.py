"""Google Calendar MCP tools backed by Google Calendar REST API."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

from mcp.server.fastmcp import FastMCP

MCP_HOST = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.getenv("MCP_PORT", "8002"))
GOOGLE_API_BASE = "https://www.googleapis.com/calendar/v3"

mcp = FastMCP(
    "google-calendar",
    instructions="Google Calendar tools for listing and managing events.",
    host=MCP_HOST,
    port=MCP_PORT,
)


def _auth_error(message: str | None = None) -> dict[str, Any]:
    return {
        "error": message or "Not authenticated. Use /connect_google in Telegram.",
        "requires_auth": True,
    }


def _json_response(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _safe_json_loads(raw: bytes) -> Any:
    if not raw:
        return {}
    text = raw.decode("utf-8", errors="replace")
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def _call_google_api(
    *,
    method: str,
    path: str,
    access_token: str,
    query: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    url = f"{GOOGLE_API_BASE}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"

    headers = {"Authorization": f"Bearer {access_token}"}
    data: bytes | None = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(url=url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=20) as response:  # noqa: S310
            status = int(getattr(response, "status", 200))
            payload = _safe_json_loads(response.read())
            return status, payload
    except HTTPError as exc:
        payload = _safe_json_loads(exc.read())
        return int(exc.code), payload
    except URLError as exc:
        return 503, {"error": f"Google Calendar API unavailable: {exc.reason}"}
    except Exception as exc:  # pragma: no cover
        return 500, {"error": f"Unexpected calendar API error: {exc}"}


def _execute_google_api(
    *,
    method: str,
    path: str,
    access_token: str,
    query: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not access_token:
        return _auth_error()

    status, payload = _call_google_api(
        method=method,
        path=path,
        access_token=access_token,
        query=query,
        body=body,
    )

    if status in (401, 403):
        return _auth_error(
            "Google token invalid or expired. Use /connect_google in Telegram."
        )
    if status >= 400:
        return {
            "error": "Google Calendar API request failed",
            "status_code": status,
            "details": payload,
        }
    if isinstance(payload, dict):
        return payload
    return {"result": payload}


@mcp.tool()
def list_calendars(access_token: str = "") -> str:
    """List user's calendars."""
    payload = _execute_google_api(
        method="GET",
        path="/users/me/calendarList",
        access_token=access_token,
    )
    if payload.get("error"):
        return _json_response(payload)

    items = payload.get("items", [])
    calendars = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            calendars.append(
                {
                    "id": item.get("id"),
                    "summary": item.get("summary"),
                    "primary": bool(item.get("primary")),
                    "accessRole": item.get("accessRole"),
                }
            )
    return _json_response({"calendars": calendars})


@mcp.tool()
def list_events(
    calendar_id: str = "primary",
    time_min: str | None = None,
    time_max: str | None = None,
    access_token: str = "",
) -> str:
    """List events from a calendar in an optional time window."""
    query: dict[str, str] = {
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": "50",
    }
    if time_min:
        query["timeMin"] = time_min
    if time_max:
        query["timeMax"] = time_max

    payload = _execute_google_api(
        method="GET",
        path=f"/calendars/{quote(calendar_id, safe='')}/events",
        access_token=access_token,
        query=query,
    )
    if payload.get("error"):
        return _json_response(payload)

    items = payload.get("items", [])
    events = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            start = item.get("start", {}) if isinstance(item.get("start"), dict) else {}
            end = item.get("end", {}) if isinstance(item.get("end"), dict) else {}
            events.append(
                {
                    "id": item.get("id"),
                    "summary": item.get("summary"),
                    "description": item.get("description"),
                    "status": item.get("status"),
                    "htmlLink": item.get("htmlLink"),
                    "start": start.get("dateTime") or start.get("date"),
                    "end": end.get("dateTime") or end.get("date"),
                }
            )

    return _json_response({"calendar_id": calendar_id, "events": events})


@mcp.tool()
def create_event(
    summary: str = "",
    start: str = "",
    end: str = "",
    calendar_id: str = "primary",
    title: str | None = None,
    description: str | None = None,
    location: str | None = None,
    reminders: list[dict[str, Any]] | None = None,
    access_token: str = "",
) -> str:
    """Create event in Google Calendar."""
    event_summary = summary.strip() or (title or "").strip()
    if not event_summary or not start or not end:
        return _json_response(
            {
                "error": (
                    "Missing required fields: summary/title, start, end "
                    "(RFC3339 date-time expected)."
                )
            }
        )

    request_body: dict[str, Any] = {
        "summary": event_summary,
        "start": {"dateTime": start},
        "end": {"dateTime": end},
    }
    if description:
        request_body["description"] = description
    if location:
        request_body["location"] = location
    if reminders is not None:
        request_body["reminders"] = {"useDefault": False, "overrides": reminders}

    payload = _execute_google_api(
        method="POST",
        path=f"/calendars/{quote(calendar_id, safe='')}/events",
        access_token=access_token,
        body=request_body,
    )
    if payload.get("error"):
        return _json_response(payload)

    start_payload = payload.get("start", {}) if isinstance(payload.get("start"), dict) else {}
    end_payload = payload.get("end", {}) if isinstance(payload.get("end"), dict) else {}
    return _json_response(
        {
            "status": "created",
            "id": payload.get("id"),
            "calendar_id": calendar_id,
            "summary": payload.get("summary") or event_summary,
            "htmlLink": payload.get("htmlLink"),
            "start": start_payload.get("dateTime") or start_payload.get("date"),
            "end": end_payload.get("dateTime") or end_payload.get("date"),
        }
    )


@mcp.tool()
def delete_event(
    event_id: str,
    calendar_id: str = "primary",
    access_token: str = "",
) -> str:
    """Delete event from Google Calendar."""
    payload = _execute_google_api(
        method="DELETE",
        path=(
            f"/calendars/{quote(calendar_id, safe='')}/events/"
            f"{quote(event_id, safe='')}"
        ),
        access_token=access_token,
    )
    if payload.get("error"):
        return _json_response(payload)
    return _json_response(
        {"status": "deleted", "calendar_id": calendar_id, "event_id": event_id}
    )

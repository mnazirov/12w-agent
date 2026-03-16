# google-calendar-mcp

SSE MCP-сервис для реальной интеграции с Google Calendar API.

## Инструменты

- `list_calendars(access_token)` -> `{"calendars": [...]}`
- `list_events(calendar_id, time_min, time_max, access_token)` -> `{"events": [...]}`
- `create_event(summary/title, start, end, calendar_id, ...)` -> `{"status":"created","id":"..."}`
- `delete_event(event_id, calendar_id, access_token)` -> `{"status":"deleted"}`

`access_token` подставляется оркестратором из OAuth (`/connect_google`).

## Запуск локально

```bash
pip install -r google_calendar_mcp/requirements.txt
python google_calendar_mcp/run.py
```

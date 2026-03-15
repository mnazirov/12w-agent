# google-calendar-mcp (mock)

В этой директории находится временный mock MCP-сервер календаря для локальной разработки.

## Что сейчас реализовано

- `list_calendars` -> `[{"id": "primary", "summary": "My Calendar"}]`
- `list_events(calendar_id, time_min, time_max)` -> `[]`
- `create_event(summary, start, end)` -> `{"status": "created", "id": "mock-123"}`
- `delete_event(event_id)` -> `{"status": "deleted"}`

## Как заменить на реальный Google Calendar MCP

1. Обновите `Dockerfile`:
   - удалите копирование `mock_server.py`
   - установите реальный пакет (через `pip install ...` или `npx ...`)
2. Оставьте тот же SSE endpoint (`/sse`) и порт `8002`.
3. Настройте переменные окружения в контейнере:
   - `GOOGLE_CREDENTIALS_PATH=/secrets/credentials.json`
   - `GOOGLE_TOKEN_PATH=/secrets/token.json`
4. При необходимости подключите volume с секретами в `docker-compose.yml`.

## Локальный запуск mock-сервера

```bash
pip install -r google_calendar_mcp/requirements.txt
python google_calendar_mcp/run.py
```

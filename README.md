# 12-Week Year Telegram Assistant

Telegram-бот для личной продуктивности по методике «12 недель в году».

## Что умеет

- `/start` — запуск и навигация
- `/setup` — настройка видения, мотивации и целей
- `/plan` — план на день
- `/checkin` — вечерний чек-ин
- `/weekly_review` — недельный обзор
- `/status` — текущий прогресс
- `/report` — аналитический отчёт за 7 дней (MCP + AI)
- `/motivation` — настройки мотивационных сообщений
- `/achievements` — сводка активности
- свободный текст — чат с AI-помощником

## Технологии

- Python 3.12
- aiogram 3.x
- OpenAI Responses API
- PostgreSQL + SQLAlchemy Async + Alembic
- MCP server (SSE) + SQLite для подсистемы мотивации
- APScheduler
- Docker / Docker Compose

## Архитектура (кратко)

Проект состоит из двух частей:

1. Основной бот
- Telegram handlers и FSM
- бизнес-логика в `app/services`
- данные пользователей и целей в PostgreSQL

2. Подсистема мотивации и аналитики
- отдельный MCP server
- трекинг активности, engagement, отчёты
- хранение мотивационных данных в SQLite

## Структура проекта

```text
12w-agent/
├── app/
│   ├── bot.py
│   ├── scheduler.py
│   ├── handlers/
│   ├── services/
│   ├── middleware/
│   └── prompts/
├── db/
├── mcp_server/
├── migrations/
├── tests/
├── docker-compose.yml
├── Dockerfile
├── Dockerfile.mcp
└── requirements.txt
```

## Быстрый старт (Docker)

1. Создайте `.env` (пример ниже).
2. Запустите:

```bash
docker compose up -d --build
```

После старта бот применяет миграции и начинает polling.

## Локальный запуск (без Docker)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python mcp_server/run.py
python main.py
```

## Минимальный `.env` пример

```bash
BOT_TOKEN=...
OPENAI_API_KEY=...
DATABASE_URL=postgresql://user:password@localhost:5432/dbname
MCP_SERVER_URL=http://localhost:8001/sse
OPENAI_MODEL=gpt-5.2
TZ=Europe/Moscow
```

## Планировщик

Регистрируются фоновые задачи:

- утреннее напоминание (`/plan`)
- вечернее напоминание (`/checkin`)
- периодическая мотивационная проверка
- еженедельная авто-сводка (`/report`)

## Аналитический пайплайн `/report`

Команда `/report` запускает цепочку:

1. сбор недельных данных из MCP
2. анализ паттернов
3. AI-инсайты
4. сохранение snapshot отчёта

Также используется сравнение с предыдущим отчётом (если доступен).

## Тесты

```bash
pytest tests/ -v
```

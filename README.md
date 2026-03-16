# 12-Week Year Telegram Assistant

Telegram-бот для личной продуктивности по методике «12 недель в году».

Проект состоит из четырёх сервисов:
- основной Telegram-бот (aiogram + PostgreSQL + OpenAI)
- отдельный MCP-сервер мотивации и аналитики (FastMCP + SQLite)
- отдельный MCP-сервер календаря (mock FastMCP, далее заменяется на реальный Google Calendar MCP)
- отдельный MCP-сервер погоды (FastMCP + Open-Meteo, без API key)

## Содержание
- [Возможности](#возможности)
- [Архитектура](#архитектура)
- [Технологический стек](#технологический-стек)
- [Структура репозитория](#структура-репозитория)
- [Требования](#требования)
- [Быстрый старт (Docker Compose)](#быстрый-старт-docker-compose)
- [Локальный запуск (без Docker)](#локальный-запуск-без-docker)
- [Конфигурация (.env)](#конфигурация-env)
- [Команды разработки и эксплуатации](#команды-разработки-и-эксплуатации)
- [Планировщик и фоновые задачи](#планировщик-и-фоновые-задачи)
- [Аналитический пайплайн `/report`](#аналитический-пайплайн-report)
- [MCP Orchestration Layer](#mcp-orchestration-layer)
- [База данных](#база-данных)
- [MCP tools (сервер мотивации)](#mcp-tools-сервер-мотивации)
- [Тестирование](#тестирование)
- [Деплой](#деплой)
- [Диагностика и типовые проблемы](#диагностика-и-типовые-проблемы)

## Возможности

### Команды бота

| Команда | Назначение |
| --- | --- |
| `/start` | Приветствие, навигация, главное меню |
| `/setup` | Многошаговая настройка: видение, зачем, цели, weekly lead actions, город |
| `/plan` | Генерация плана на день с учётом календаря/погоды (`/plan <город>` для одноразового override) |
| `/checkin` | Вечерний чек-ин с анализом и WOOP |
| `/weekly_review` | Недельный обзор и рефлексия |
| `/clear` | Сброс контекста свободного чата (цели и прогресс сохраняются) |
| `/status` | Текущий прогресс по спринту и задачам |
| `/report` | Аналитический отчёт за 7 дней (MCP + AI insights) |
| `/motivation` | Настройки мотивационных сообщений |
| `/achievements` | Сводка активности/вовлечённости за 7 дней |
| `/connect_google` | Подключение Google-аккаунта для работы с календарём |
| `/disconnect_google` | Отключение Google-аккаунта |
| `/google_status` | Текущий статус Google-подключения |

Также поддерживается свободный текст (fallback-чат с AI):
- сохраняется контекст диалога между сообщениями (Responses API `previous_response_id`)
- в каждый запрос добавляется пользовательский контекст из memory records + активные цели
- сессия автоматически сбрасывается после таймаута или командой `/clear`
- встроен антиспам-лимит: до 15 сообщений в минуту на пользователя

## Архитектура

```mermaid
graph TD
    U[Telegram User] --> B[Bot: aiogram]
    B --> H[Handlers]
    H --> S[App Services]
    S --> DB[(PostgreSQL)]
    S --> OA[OpenAI Responses API]
    S --> ORC[MCP Orchestrator]
    ORC --> MC1[MCP motivation]
    ORC --> MC2[MCP calendar]
    ORC --> MC3[MCP weather]
    MC1 --> MS[MCP Server FastMCP]
    MC2 --> GMS[Google Calendar MCP Mock]
    MC3 --> WM[Open-Meteo API]
    MS --> SQ[(SQLite)]
    B --> SCH[APScheduler]
    SCH --> S
```

### Ключевые потоки
- Handlers принимают команды/события Telegram.
- Бизнес-логика выполняется в `app/services`.
- Данные бота хранятся в PostgreSQL (`db/models.py`, `db/repos.py`).
- MCP вызовы идут через orchestration-слой (`app/services/mcp_orchestrator.py`) с auto-routing tools.
- Подсистема мотивации и аналитики вынесена в отдельный MCP-сервер на SQLite (`mcp_server/server.py`).
- Календарный MCP-сервис запускается отдельно (`google_calendar_mcp/`) и работает через Google Calendar API.
- Погодный MCP-сервис запускается отдельно (`weather_mcp/`) и обращается к Open-Meteo.
- Планировщик APScheduler шлёт напоминания и запускает периодические задачи.

## Технологический стек

- Python 3.12
- aiogram 3.x
- OpenAI Python SDK (`AsyncOpenAI`, Responses API)
- SQLAlchemy Async + asyncpg
- Alembic
- APScheduler
- MCP (`FastMCP`) + SSE transport
- PostgreSQL (основные данные)
- SQLite (мотивация/аналитика в MCP-сервисе)
- Docker / Docker Compose
- GitHub Actions (деплой по SSH)

Зависимости (из `requirements.txt`):
- `aiogram>=3.13,<4`
- `openai>=1.55`
- `python-dotenv>=1.0`
- `asyncpg>=0.30`
- `apscheduler>=3.10`
- `sqlalchemy[asyncio]>=2.0`
- `alembic>=1.13`
- `pydantic>=2.0`
- `mcp>=1.0.0`

## Структура репозитория

```text
12w-agent/
├── app/
│   ├── bot.py                     # Инициализация бота, роутеры, scheduler
│   ├── config.py                  # Загрузка env-конфига
│   ├── scheduler.py               # Напоминания + мотивационные/weekly jobs
│   ├── states.py                  # FSM состояния
│   ├── keyboards.py               # Inline-клавиатуры
│   ├── handlers/                  # Telegram handlers
│   ├── middleware/                # Activity tracking middleware
│   ├── services/                  # Бизнес-логика
│   │   ├── mcp_client.py          # MCP клиент (SSE, tools/list, call_tool)
│   │   └── mcp_orchestrator.py    # Реестр MCP серверов + routing tools
│   └── prompts/                   # Prompt templates для OpenAI
├── db/
│   ├── models.py                  # ORM модели PostgreSQL
│   ├── repos.py                   # Репозиторный слой
│   └── base.py                    # Async engine/session factory
├── mcp_server/
│   ├── server.py                  # MCP tools + SQLite schema + аналитика
│   └── run.py                     # Запуск MCP сервера
├── google_calendar_mcp/
│   ├── mock_server.py             # Google Calendar MCP tools
│   ├── run.py                     # Запуск calendar MCP сервера
│   └── Dockerfile                 # Контейнер календарного сервиса
├── weather_mcp/
│   ├── server.py                  # Weather MCP tools (Open-Meteo)
│   ├── run.py                     # Запуск weather MCP сервера
│   ├── Dockerfile                 # Контейнер weather сервиса
│   └── requirements.txt           # Зависимости weather сервиса
├── migrations/                    # Alembic migrations
├── tests/                         # pytest тесты
├── scripts/deploy.sh              # Скрипт деплоя
├── docker-compose.yml
├── Dockerfile
├── Dockerfile.mcp
├── requirements.txt
└── main.py                        # Entry point
```

## Требования

- Python 3.12+
- Docker + Docker Compose (для контейнерного запуска)
- PostgreSQL (если запуск без Docker)
- Доступ к OpenAI API
- Telegram bot token

## Быстрый старт (Docker Compose)

### 1. Создайте `.env` в корне

Минимально необходимый пример:

```bash
BOT_TOKEN=...
OPENAI_API_KEY=...
DATABASE_URL=postgresql://12w:12w@postgres:5432/12w
MCP_SERVER_URL=http://mcp-server:8001/sse
GOOGLE_CALENDAR_MCP_URL=http://google-calendar-mcp:8002/sse
WEATHER_MCP_URL=http://weather-mcp:8003/sse
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=https://<ngrok-domain>/oauth/google/callback
GOOGLE_TOKENS_ENCRYPTION_KEY=
OAUTH_CALLBACK_PORT=8080
NGROK_AUTHTOKEN=
NGROK_DOMAIN=<ngrok-domain>   # обязателен для OAuth через ngrok (только host, без https:// и /)
OPENAI_MODEL=gpt-5.2
TZ=Europe/Moscow
```

### 2. Поднимите сервисы

```bash
docker compose up -d --build
```

Если используете OAuth через ngrok, запускайте профиль `ngrok`:

```bash
docker compose --profile ngrok up -d --build
```

Состав сервисов:
- `postgres` (`postgres:16-alpine`)
- `mcp-server` (из `Dockerfile.mcp`)
- `google-calendar-mcp` (из `google_calendar_mcp/Dockerfile`)
- `weather-mcp` (из `weather_mcp/Dockerfile`)
- `bot` (из `Dockerfile`)
- `ngrok` (опционально, профиль `ngrok`, проксирует `bot:8080` наружу)

### 3. Проверьте состояние

```bash
docker compose ps
docker compose logs --tail=200 bot
docker compose logs --tail=200 mcp-server
```

### 4. Остановить

```bash
docker compose down
```

## Локальный запуск (без Docker)

### 1. Создайте виртуальное окружение

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Подготовьте переменные окружения

Создайте `.env` и заполните обязательные параметры (`BOT_TOKEN`, `OPENAI_API_KEY`, `DATABASE_URL`).

### 3. Примените миграции PostgreSQL

```bash
alembic upgrade head
```

### 4. Запустите MCP-серверы

```bash
python mcp_server/run.py
```

В отдельном терминале запустите weather MCP:

```bash
python weather_mcp/run.py
```

### 5. Запустите бота

В отдельном терминале:

```bash
python main.py
```

## Конфигурация (.env)

### Переменные основного бота (`app/config.py`)

| Переменная | Обязательна | Значение по умолчанию | Назначение |
| --- | --- | --- | --- |
| `BOT_TOKEN` | Да | `""` | Telegram bot token |
| `OPENAI_API_KEY` | Да (для AI-функций) | `""` | Ключ OpenAI |
| `OPENAI_MODEL` | Нет | `gpt-5.2` | Модель для OpenAI вызовов |
| `OPENAI_MAX_TOKENS` | Нет | `1024` | Лимит `max_output_tokens` |
| `OPENAI_TIMEOUT` | Нет | `60` | Таймаут OpenAI клиента (сек.) |
| `DATABASE_URL` | Да | `""` | Подключение к PostgreSQL |
| `MCP_SERVER_URL` | Нет | `http://mcp-server:8001/sse` | SSE endpoint MCP сервера |
| `GOOGLE_CALENDAR_MCP_URL` | Нет | `http://google-calendar-mcp:8002/sse` | SSE endpoint calendar MCP сервера |
| `WEATHER_MCP_URL` | Нет | `http://weather-mcp:8003/sse` | SSE endpoint weather MCP сервера |
| `GOOGLE_CLIENT_ID` | Для OAuth | `""` | Google OAuth client id |
| `GOOGLE_CLIENT_SECRET` | Для OAuth | `""` | Google OAuth client secret |
| `GOOGLE_REDIRECT_URI` | Для OAuth | `""` | Callback URL (`https://.../oauth/google/callback`) |
| `GOOGLE_TOKENS_ENCRYPTION_KEY` | Для OAuth | `""` | Fernet-ключ для шифрования токенов в БД |
| `OAUTH_CALLBACK_PORT` | Нет | `8080` | Порт aiohttp callback-сервера внутри bot-контейнера |
| `TZ` | Нет | `Europe/Moscow` | Таймзона scheduler |
| `REMINDER_PLAN_HOUR` | Нет | `9` | Час утреннего reminder |
| `REMINDER_PLAN_MINUTE` | Нет | `0` | Минуты утреннего reminder |
| `REMINDER_RESULTS_HOUR` | Нет | `21` | Час вечернего reminder |
| `REMINDER_RESULTS_MINUTE` | Нет | `0` | Минуты вечернего reminder |
| `MEMORY_CONTEXT_MAX_TOKENS` | Нет | `500` | Бюджет контекста memory-сервиса |
| `MAX_HISTORY_DAYS` | Нет | `14` | Сколько дней memory учитывать |

### Переменные MCP-сервера (`mcp_server/server.py`, `mcp_server/run.py`)

| Переменная | Обязательна | Значение по умолчанию | Назначение |
| --- | --- | --- | --- |
| `MCP_HOST` | Нет | `0.0.0.0` | Host MCP-сервера |
| `MCP_PORT` | Нет | `8001` | Port MCP-сервера |
| `MCP_DB_PATH` | Нет | `/data/motivation.db` | Путь к SQLite БД MCP |

### Переменные Docker Compose (`docker-compose.yml`)

| Переменная | Значение по умолчанию | Где используется |
| --- | --- | --- |
| `POSTGRES_USER` | `12w` | сервис `postgres` |
| `POSTGRES_PASSWORD` | `12w` | сервис `postgres` |
| `POSTGRES_DB` | `12w` | сервис `postgres` |
| `GOOGLE_CREDENTIALS_PATH` | `/secrets/credentials.json` | сервис `google-calendar-mcp` |
| `GOOGLE_TOKEN_PATH` | `/secrets/token.json` | сервис `google-calendar-mcp` |
| `OAUTH_CALLBACK_PORT` | `8080` | сервис `bot` (порт callback endpoint) |
| `NGROK_AUTHTOKEN` | `""` | сервис `ngrok` (обязателен при использовании профиля `ngrok`) |
| `NGROK_DOMAIN` | `""` | сервис `ngrok` (обязателен для стабильного OAuth redirect) |

## Команды разработки и эксплуатации

### Установка зависимостей

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Сборка/запуск контейнеров

```bash
docker compose up -d --build
```

### Локальный запуск

```bash
alembic upgrade head
python mcp_server/run.py
python weather_mcp/run.py
python main.py
```

### Тесты

Все тесты:

```bash
pytest tests/ -v
```

Один файл тестов:

```bash
pytest tests/test_planning_service.py -v
```

Один тест:

```bash
pytest tests/test_planning_service.py::TestDailyPlanResponse::test_valid_plan -v
```

### Линтер/форматтер/type-check

На текущем состоянии репозитория отдельные команды линтинга, форматирования и type-checking не настроены (нет конфигов `ruff`, `black`, `mypy`, `pyright`, `flake8`, `pyproject.toml`).

## Планировщик и фоновые задачи

Фоновые задачи регистрируются в `app/scheduler.py`:

- Утреннее напоминание о плане (`/plan`) по `REMINDER_PLAN_HOUR:REMINDER_PLAN_MINUTE`
- Вечернее напоминание о чек-ине (`/checkin`) по `REMINDER_RESULTS_HOUR:REMINDER_RESULTS_MINUTE`
- Проверка мотивации каждую минуту (`register_motivation_job`)
- Еженедельный авто-отчёт по воскресеньям в 20:00 (`register_weekly_report_job`)

## Аналитический пайплайн `/report`

Оркестрация: `app/services/pipeline_service.py`.

Шаги:
1. `collect_week_data` (MCP) — сбор сырых данных
2. `analyze_patterns` (MCP) — вычисление метрик и рекомендаций
3. OpenAI insights — генерация текстовых выводов
4. `save_weekly_report` (MCP) — сохранение snapshot

Дополнительно:
- попытка подтянуть `get_previous_reports` для сравнения с предыдущей неделей
- при падении шага возвращается `success=False` + `error`

## MCP Orchestration Layer

`app/services/mcp_orchestrator.py` агрегирует несколько MCP-серверов:
- `motivation` -> `MCP_SERVER_URL`
- `calendar` -> `GOOGLE_CALENDAR_MCP_URL`
- `weather` -> `WEATHER_MCP_URL`

Что делает оркестратор:
- подключается к каждому серверу независимо (`connect_all` / `disconnect_all`)
- делает discovery через `tools/list`
- строит единый каталог tools для OpenAI (с обработкой коллизий имён)
- маршрутизирует tool calls по имени (`call_tool`)
- поддерживает прямые legacy-вызовы на конкретный сервер (`call_tool_on_server`)

## Google OAuth2

Подключение пользователя к Google запускается командой `/connect_google`.

Поток:
1. Бот генерирует Google consent URL (`access_type=offline`, `prompt=consent`) и отправляет кнопку.
2. Пользователь проходит авторизацию в Google.
3. Google редиректит на `GET /oauth/google/callback` (aiohttp сервер внутри bot-контейнера, порт `8080`).
4. Бот обменивает `code` на токены, шифрует их (`Fernet`) и сохраняет в PostgreSQL (`google_tokens`).
5. При вызовах calendar-tools оркестратор автоматически запрашивает валидный access token (с refresh при необходимости) и инжектирует `_access_token`.

Безопасность:
- Токены в БД хранятся только в зашифрованном виде.
- Ключ шифрования берётся из `GOOGLE_TOKENS_ENCRYPTION_KEY`.
- Токены не логируются.

### Настройка Google Cloud Console

1. Создайте OAuth 2.0 Client ID (тип: Web application).
2. В `Authorized redirect URIs` добавьте:
   - `https://your-domain.com/oauth/google/callback` (prod)
   - `https://<ngrok-domain>/oauth/google/callback` (dev)
3. Выдайте приложению scopes:
   - `https://www.googleapis.com/auth/calendar.events`
   - `openid`
   - `email`
4. Сгенерируйте ключ Fernet:
   - `python -c "from app.services.crypto_service import TokenEncryptor; print(TokenEncryptor.generate_key())"`
5. Заполните env-переменные OAuth в `.env`.

### Запуск OAuth через ngrok (без домена)

1. Укажите в `.env`:
   - `NGROK_AUTHTOKEN=<ваш токен ngrok>`
   - `NGROK_DOMAIN=<ваш закреплённый ngrok-домен>` (обязательно, только host)
   - `GOOGLE_REDIRECT_URI=https://<ngrok-domain>/oauth/google/callback`
2. Запускайте стек с профилем:
   - `docker compose --profile ngrok up -d --build`
3. Убедитесь, что в Google Cloud Console в `Authorized redirect URIs` указан тот же URL.

## База данных

### PostgreSQL (основной контур)

Модели в `db/models.py`, миграции в `migrations/versions/`.

Таблицы:
- `users`
- `google_tokens`
- `vision_and_why`
- `goals_12w`
- `weekly_plans`
- `daily_plans`
- `checkins`
- `memory_records`
- `sprints` (добавлена миграцией `002_add_sprints.py`)

### SQLite (MCP-контур)

Инициализируется в `mcp_server/server.py`.

Таблицы:
- `activity_log`
- `motivation_config`
- `motivation_history`
- `achievement_snapshots`

## MCP tools (сервер мотивации)

Инструменты, доступные в MCP-сервере (`mcp_server/server.py`):
- `log_activity`
- `log_activities_batch`
- `get_achievement_report`
- `get_today_actions`
- `check_engagement`
- `generate_motivation_context`
- `get_motivation_config`
- `update_motivation_config`
- `record_motivation_sent`
- `get_users_needing_motivation`
- `collect_week_data`
- `analyze_patterns`
- `save_weekly_report`
- `get_previous_reports`

## Тестирование

Тесты расположены в `tests/`:
- `test_planning_service.py`
- `test_checkin_service.py`
- `test_review_service.py`
- `test_mcp_orchestrator.py`
- `test_crypto_service.py`
- `test_google_auth_service.py`
- `test_oauth_callback.py`
- `conftest.py`

Текущее покрытие в основном проверяет:
- Pydantic-валидацию structured output
- форматирование сообщений для Telegram

Полноценные интеграционные тесты с реальным PostgreSQL/MCP/OpenAI пока не реализованы.

## Деплой

### CI/CD

GitHub Actions workflow: `.github/workflows/deploy.yml`.

Триггеры:
- push в `main`
- ручной `workflow_dispatch`

Сценарий деплоя:
- SSH-подключение к VPS через `appleboy/ssh-action`
- запуск `scripts/deploy.sh main` на сервере

### Серверный скрипт деплоя

`scripts/deploy.sh` выполняет:
1. выбор `docker compose` или `docker-compose`
2. `git fetch`/`checkout`/`pull --ff-only`
3. `docker compose up -d --build`
4. при ошибке печатает `ps` и хвост логов `mcp-server`/`bot`

## Диагностика и типовые проблемы

### 1) Бот не стартует: `BOT_TOKEN is not set`
- Проверьте `.env`
- Убедитесь, что `BOT_TOKEN` доступен процессу

### 2) Ошибка подключения к PostgreSQL
- Проверьте `DATABASE_URL`
- Убедитесь, что PostgreSQL доступен
- Примените миграции: `alembic upgrade head`

### 3) MCP недоступен
- Проверьте `MCP_SERVER_URL`
- Проверьте, что MCP-сервер поднят (`python mcp_server/run.py` или контейнер `mcp-server`)
- Посмотрите логи: `docker compose logs --tail=200 mcp-server`

### 4) Ошибки `/report`
- Проверьте MCP-инструменты `collect_week_data`, `analyze_patterns`, `save_weekly_report`
- Посмотрите обработку ошибок в `app/services/pipeline_service.py`

### 5) `/connect_google` сообщает «OAuth не настроен»
- Проверьте env: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `GOOGLE_TOKENS_ENCRYPTION_KEY`
- Убедитесь, что callback endpoint доступен по HTTPS и совпадает с Google Console

### 6) Некорректный AI JSON
- Проверьте prompt-файлы в `app/prompts/`
- Проверьте соответствующую Pydantic-модель в `app/services/*_service.py`
- Проверьте retry-логику в `app/services/openai_service.py`

## Полезные точки входа в код

- `main.py` — старт приложения
- `app/bot.py` — сборка dispatcher/routers/middleware/scheduler
- `app/config.py` — env-конфиг
- `db/models.py` / `db/repos.py` — доменная модель и репозитории
- `mcp_server/server.py` — MCP API + SQLite аналитика

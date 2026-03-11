# 12-Week Year Telegram Assistant

Telegram-бот — персональный коуч по методике «12 недель в году» с элементами поведенческой науки: implementation intentions, WOOP, timeboxing, friction reduction, spaced review.

## Стек

- **Python 3.12**, aiogram 3 (FSM + inline keyboards)
- **OpenAI API** (Responses API, `gpt-5.2` по умолчанию)
- **PostgreSQL 16** + SQLAlchemy async + Alembic
- **Docker Compose** для деплоя на VPS
- **APScheduler** для утренних/вечерних напоминаний
- **Pydantic** для валидации AI-ответов

## Архитектура

```
12w-agent/
├── app/
│   ├── bot.py              # Сборка Dispatcher + роутеры
│   ├── config.py            # Конфигурация из .env
│   ├── scheduler.py         # Напоминания (cron)
│   ├── states.py            # FSM StatesGroup
│   ├── keyboards.py         # Inline-клавиатуры
│   ├── handlers/            # Обработчики команд
│   │   ├── start.py         # /start
│   │   ├── setup.py         # /setup (vision → why → goals → lead actions)
│   │   ├── plan.py          # /plan (AI-план дня)
│   │   ├── checkin.py       # /checkin (вечерний чек-ин + WOOP)
│   │   ├── weekly_review.py # /weekly_review (недельный обзор)
│   │   ├── status.py        # /status (прогресс)
│   │   └── chat.py          # Свободный AI-чат
│   ├── services/
│   │   ├── openai_service.py    # OpenAI обёртка + JSON валидация
│   │   ├── planning_service.py  # Генерация дневного плана
│   │   ├── checkin_service.py   # Анализ чек-ина + WOOP
│   │   ├── review_service.py    # Недельный scoring + рефлексия
│   │   └── memory_service.py    # Суммаризация и контекст
│   └── prompts/             # Шаблоны промптов (.md)
├── db/
│   ├── base.py              # AsyncEngine + sessionmaker
│   ├── models.py            # SQLAlchemy ORM (8 таблиц)
│   └── repos.py             # CRUD-функции
├── migrations/              # Alembic миграции
├── tests/                   # Unit-тесты
├── main.py                  # Точка входа
├── alembic.ini
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

## Быстрый старт

### 1. Настройка .env

```bash
touch .env
# Заполните:
#   BOT_TOKEN=...       (от @BotFather)
#   OPENAI_API_KEY=...  (ключ OpenAI)
#   POSTGRES_USER=...
#   POSTGRES_PASSWORD=...
#   DATABASE_URL=...
```

### 2. Docker (рекомендуется)

```bash
docker compose up -d
# Миграции применяются автоматически при старте бота
```

### 3. Локальный запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Запустите PostgreSQL и задайте DATABASE_URL в .env
export DATABASE_URL=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:5432/12w

# Применить миграции
alembic upgrade head

# Запуск
python main.py
```

### 4. Обновление на VPS

```bash
git pull
docker compose build --no-cache bot
docker compose up -d
```

Или через скрипт из репозитория:

```bash
APP_DIR=/opt/12w-agent ./scripts/deploy.sh main
```

### 5. Автодеплой из GitHub (push -> VPS)

В репозитории есть workflow [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml), который срабатывает на `push` в `main` и деплоит проект на сервер по SSH.

Добавьте Secrets в GitHub (`Settings -> Secrets and variables -> Actions`):
- `VPS_HOST` — IP/домен сервера
- `VPS_USER` — SSH-пользователь на VPS
- `VPS_SSH_KEY` — приватный ключ (рекомендуется отдельный deploy key)
- `VPS_PORT` — опционально, по умолчанию `22`
- `VPS_APP_DIR` — опционально, по умолчанию `/opt/12w-agent`

## Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие + меню |
| `/setup` | Настроить видение, мотивацию (why), цели и еженедельные действия (FSM-поток) |
| `/plan` | Сгенерировать план на сегодня (Top-3 + extras + timeblocks) |
| `/checkin` | Вечерний чек-ин: отметить задачи → препятствия → WOOP → урок → уверенность |
| `/weekly_review` | Недельный обзор: scoring + AI-рефлексия + корректировки |
| `/status` | Прогресс: неделя X/12, % lead actions, streak, видение |
| Свободный текст | AI-чат с контекстом целей |

## Поведенческие методики

- **Implementation Intentions** — каждая задача в плане имеет формулу «Я сделаю X в Y в Z»
- **WOOP** — для пропущенных задач: Wish → Outcome → Obstacle → Plan
- **Starter Step** — 2-минутная версия задачи для преодоления сопротивления
- **Friction Reduction** — ежедневная рекомендация по изменению среды
- **Timeboxing** — временные слоты для Top-3 задач
- **Cognitive Load** — лимит: 3 приоритетных + 2 дополнительных задачи
- **Spaced Review** — еженедельный обзор + напоминание о mid-point (неделя 6)
- **Attribution** — разделение контролируемых и неконтролируемых факторов

## Напоминания

По умолчанию (настраивается через .env):
- **09:00** — «Пора составить план на день»
- **21:00** — «Пора подвести итоги дня»

Переменные: `REMINDER_PLAN_HOUR`, `REMINDER_PLAN_MINUTE`, `REMINDER_RESULTS_HOUR`, `REMINDER_RESULTS_MINUTE`, `TZ`.

## Тесты

```bash
pip install pytest pytest-asyncio
pytest tests/ -v
```

## Переменные окружения

| Переменная | По умолчанию | Описание |
|-----------|-------------|----------|
| `BOT_TOKEN` | — | Токен Telegram-бота |
| `OPENAI_API_KEY` | — | Ключ OpenAI API |
| `POSTGRES_USER` | 12w | Пользователь PostgreSQL (для docker-compose) |
| `POSTGRES_PASSWORD` | 12w | Пароль PostgreSQL (для docker-compose) |
| `DATABASE_URL` | — | URL PostgreSQL |
| `OPENAI_MODEL` | gpt-5.2 | Модель OpenAI |
| `OPENAI_MAX_TOKENS` | 1024 | Макс. токенов в ответе |
| `OPENAI_TIMEOUT` | 60 | Таймаут OpenAI API (секунды) |
| `TZ` | Europe/Moscow | Таймзона |
| `REMINDER_PLAN_HOUR` | 9 | Час утреннего напоминания |
| `REMINDER_PLAN_MINUTE` | 0 | Минуты утреннего напоминания |
| `REMINDER_RESULTS_HOUR` | 21 | Час вечернего напоминания |
| `REMINDER_RESULTS_MINUTE` | 0 | Минуты вечернего напоминания |
| `MEMORY_CONTEXT_MAX_TOKENS` | 500 | Бюджет токенов для контекста памяти |
| `MAX_HISTORY_DAYS` | 14 | Дней истории для контекста |

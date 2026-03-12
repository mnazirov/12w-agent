"""Bot assembly: Dispatcher, routers, scheduler, lifecycle."""
from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from app.config import BOT_TOKEN, MCP_SERVER_URL, OPENAI_MODEL
from app.handlers import get_all_routers
from app.handlers.motivation import router as motivation_router
from app.middleware.activity_tracker import ActivityTrackerMiddleware
from app.scheduler import (
    register_motivation_job,
    register_weekly_report_job,
    setup_scheduler,
    shutdown_scheduler,
)
from app.services.mcp_client import MCPMotivationClient
from app.services.openai_service import get_client
from db.base import close_engine, get_engine, get_session_factory
from db.repos import get_user_by_telegram_id, get_vision

logger = logging.getLogger(__name__)


class _OpenAIServiceAdapter:
    """Adapter exposing chat(system, user, max_tokens) for scheduler jobs."""

    async def chat(self, system: str, user: str, max_tokens: int = 300) -> str:
        client = get_client()
        response = await client.responses.create(
            model=OPENAI_MODEL,
            instructions=system,
            input=user,
            max_output_tokens=max_tokens,
        )
        return (response.output_text or "").strip()


class _UserRepoAdapter:
    """Adapter for retrieving user vision by Telegram id."""

    async def get_vision_text(self, telegram_id: int) -> str | None:
        async with get_session_factory()() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                return None
            vision = await get_vision(session, user.id)
            return vision.vision if vision else None


async def _set_bot_commands(bot: Bot) -> None:
    """Set Telegram command menu for the assistant."""
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="🚀 Запуск"),
            BotCommand(command="setup", description="🎯 Настроить цели"),
            BotCommand(command="plan", description="📝 План на день"),
            BotCommand(command="checkin", description="✅ Вечерний чек-ин"),
            BotCommand(command="weekly_review", description="📋 Недельный обзор"),
            BotCommand(command="status", description="📈 Статус и прогресс"),
            BotCommand(command="report", description="📊 Аналитический отчёт за неделю"),
            BotCommand(command="motivation", description="⚙️ Настройки мотивации"),
            BotCommand(command="achievements", description="📊 Сводка достижений"),
        ]
    )


async def run_bot() -> None:
    """Initialize and start the bot (long-running)."""
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is not set. Add it to .env")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Ensure the engine is created (validates DB connectivity)
    get_engine()

    bot = Bot(token=BOT_TOKEN)
    try:
        await _set_bot_commands(bot)
    except Exception as exc:
        logger.warning("Failed to set bot commands: %s", exc)

    mcp_client = MCPMotivationClient(MCP_SERVER_URL)
    openai_service = _OpenAIServiceAdapter()
    user_repo = _UserRepoAdapter()

    dp = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(ActivityTrackerMiddleware(mcp_client))
    dp.callback_query.middleware(ActivityTrackerMiddleware(mcp_client))
    dp.workflow_data["mcp_client"] = mcp_client
    dp.workflow_data["openai_service"] = openai_service
    dp.workflow_data["user_repo"] = user_repo

    # Register routers
    dp.include_router(motivation_router)
    for router in get_all_routers():
        dp.include_router(router)

    # Setup scheduler (reminders)
    scheduler = setup_scheduler(bot)
    register_motivation_job(
        scheduler=scheduler,
        bot=bot,
        mcp_client=mcp_client,
        openai_service=openai_service,
        user_repo=user_repo,
    )
    register_weekly_report_job(
        scheduler=scheduler,
        bot=bot,
        mcp_client=mcp_client,
        openai_service=openai_service,
        user_repo=user_repo,
    )

    try:
        logger.info("Starting bot polling…")
        await dp.start_polling(bot)
    finally:
        shutdown_scheduler(scheduler)
        await close_engine()
        logger.info("Bot stopped.")

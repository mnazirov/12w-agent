"""Bot assembly: Dispatcher, routers, scheduler, lifecycle."""
from __future__ import annotations

import logging
from datetime import datetime

from aiohttp import web

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from app.config import (
    BOT_TOKEN,
    CHAT_RATE_LIMIT_PER_MINUTE,
    CHAT_SESSION_TIMEOUT_MINUTES,
    GOOGLE_CALENDAR_MCP_URL,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REDIRECT_URI,
    GOOGLE_TOKENS_ENCRYPTION_KEY,
    MCP_SERVER_URL,
    OAUTH_CALLBACK_PORT,
    OPENAI_MODEL,
    WEATHER_MCP_URL,
)
from app.handlers import get_all_routers
from app.handlers.motivation import router as motivation_router
from app.middleware.activity_tracker import ActivityTrackerMiddleware
from app.middleware.rate_limit import ChatRateLimiter
from app.scheduler import (
    register_motivation_job,
    register_weekly_report_job,
    setup_scheduler,
    shutdown_scheduler,
)
from app.services.crypto_service import TokenEncryptor
from app.services.google_auth_service import GoogleAuthService
from app.services.chat_context_service import ChatContextService
from app.services.message_cleanup import TrackingBot
from app.services.mcp_client import MCPMotivationClient
from app.services.mcp_orchestrator import MCPOrchestrator
from app.services.openai_service import get_client
from app.web.oauth_callback import routes as oauth_routes
from db.base import close_engine, get_engine, get_session_factory
from db import repos

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
            user = await repos.get_user_by_telegram_id(session, telegram_id)
            if not user:
                return None
            vision = await repos.get_vision(session, user.id)
            return vision.vision if vision else None

    async def get_vision(self, telegram_id: int):
        async with get_session_factory()() as session:
            user = await repos.get_user_by_telegram_id(session, telegram_id)
            if not user:
                return None
            return await repos.get_vision(session, user.id)


class _GoogleAuthRepoAdapter:
    """Repository adapter with session management for GoogleAuthService."""

    async def get_user_by_telegram_id(self, telegram_id: int):
        async with get_session_factory()() as session:
            return await repos.get_user_by_telegram_id(session, telegram_id)

    async def save_google_tokens(
        self,
        user_id: int,
        telegram_id: int,
        access_token_enc: str,
        refresh_token_enc: str,
        token_expiry: datetime,
        google_email: str | None,
        scopes: str,
    ) -> None:
        async with get_session_factory()() as session:
            await repos.save_google_tokens(
                session=session,
                user_id=user_id,
                telegram_id=telegram_id,
                access_token_enc=access_token_enc,
                refresh_token_enc=refresh_token_enc,
                token_expiry=token_expiry,
                google_email=google_email,
                scopes=scopes,
            )
            await session.commit()

    async def get_google_tokens(self, user_id: int):
        async with get_session_factory()() as session:
            return await repos.get_google_tokens(session, user_id)

    async def update_google_access_token(
        self,
        user_id: int,
        access_token_enc: str,
        token_expiry: datetime,
    ) -> None:
        async with get_session_factory()() as session:
            await repos.update_google_access_token(
                session=session,
                user_id=user_id,
                access_token_enc=access_token_enc,
                token_expiry=token_expiry,
            )
            await session.commit()

    async def delete_google_tokens(self, user_id: int) -> None:
        async with get_session_factory()() as session:
            await repos.delete_google_tokens(session, user_id)
            await session.commit()

    async def has_google_connected(self, user_id: int) -> bool:
        async with get_session_factory()() as session:
            return await repos.has_google_connected(session, user_id)


async def _start_oauth_server(
    bot: Bot,
    google_auth_service: GoogleAuthService,
    port: int,
    chat_context_service: ChatContextService | None = None,
) -> web.AppRunner:
    """Run OAuth callback HTTP server in parallel with bot polling."""
    app_web = web.Application()
    app_web.add_routes(oauth_routes)
    app_web["bot"] = bot
    app_web["google_auth_service"] = google_auth_service
    app_web["chat_context_service"] = chat_context_service

    runner = web.AppRunner(app_web)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("OAuth callback server started on :%d", port)
    return runner


async def _set_bot_commands(bot: Bot) -> None:
    """Set Telegram command menu for the assistant."""
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="🚀 Запуск"),
            BotCommand(command="setup", description="🎯 Настроить цели"),
            BotCommand(command="plan", description="📝 План на день"),
            BotCommand(command="checkin", description="✅ Вечерний чек-ин"),
            BotCommand(command="weekly_review", description="📋 Недельный обзор"),
            BotCommand(command="clear", description="🧹 Очистить контекст чата"),
            BotCommand(command="status", description="📈 Статус и прогресс"),
            BotCommand(command="report", description="📊 Аналитический отчёт за неделю"),
            BotCommand(command="motivation", description="⚙️ Настройки мотивации"),
            BotCommand(command="achievements", description="📊 Сводка достижений"),
            BotCommand(command="connect_google", description="🔗 Подключить Google-аккаунт"),
            BotCommand(command="disconnect_google", description="🔓 Отключить Google"),
            BotCommand(command="google_status", description="🗓 Статус Google"),
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

    bot = TrackingBot(token=BOT_TOKEN)
    try:
        await _set_bot_commands(bot)
    except Exception as exc:
        logger.warning("Failed to set bot commands: %s", exc)

    chat_context_service = ChatContextService(
        session_factory=get_session_factory(),
        session_timeout_minutes=CHAT_SESSION_TIMEOUT_MINUTES,
    )

    google_auth_service: GoogleAuthService | None = None
    oauth_runner: web.AppRunner | None = None

    if (
        GOOGLE_CLIENT_ID
        and GOOGLE_CLIENT_SECRET
        and GOOGLE_REDIRECT_URI
        and GOOGLE_TOKENS_ENCRYPTION_KEY
    ):
        try:
            encryptor = TokenEncryptor(GOOGLE_TOKENS_ENCRYPTION_KEY)
            google_auth_service = GoogleAuthService(
                client_id=GOOGLE_CLIENT_ID,
                client_secret=GOOGLE_CLIENT_SECRET,
                redirect_uri=GOOGLE_REDIRECT_URI,
                encryptor=encryptor,
                repo=_GoogleAuthRepoAdapter(),
            )
            await google_auth_service.start()
            oauth_runner = await _start_oauth_server(
                bot=bot,
                google_auth_service=google_auth_service,
                port=OAUTH_CALLBACK_PORT,
                chat_context_service=chat_context_service,
            )
        except Exception as exc:
            logger.exception("Failed to initialize Google OAuth service: %s", exc)
            if google_auth_service is not None:
                await google_auth_service.stop()
            google_auth_service = None
    else:
        logger.warning(
            "Google OAuth not configured: set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, "
            "GOOGLE_REDIRECT_URI, GOOGLE_TOKENS_ENCRYPTION_KEY"
        )

    mcp_orchestrator = MCPOrchestrator(google_auth_service=google_auth_service)
    await mcp_orchestrator.register_server(
        name="motivation",
        url=MCP_SERVER_URL,
        description="Motivation tracker MCP server",
    )
    await mcp_orchestrator.register_server(
        name="calendar",
        url=GOOGLE_CALENDAR_MCP_URL,
        description="Google Calendar MCP server",
    )
    await mcp_orchestrator.register_server(
        name="weather",
        url=WEATHER_MCP_URL,
        description="Погода: прогноз и оценка условий для тренировок",
    )
    await mcp_orchestrator.connect_all()

    mcp_client = mcp_orchestrator.motivation or MCPMotivationClient(
        MCP_SERVER_URL,
        persistent=True,
        reconnect_attempts=1,
    )
    openai_service = _OpenAIServiceAdapter()
    user_repo = _UserRepoAdapter()
    chat_rate_limiter = ChatRateLimiter(max_per_minute=CHAT_RATE_LIMIT_PER_MINUTE)

    dp = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(ActivityTrackerMiddleware(mcp_client, chat_context_service))
    dp.callback_query.middleware(ActivityTrackerMiddleware(mcp_client))
    dp.workflow_data["mcp_client"] = mcp_client
    dp.workflow_data["mcp_orchestrator"] = mcp_orchestrator
    dp.workflow_data["openai_service"] = openai_service
    dp.workflow_data["user_repo"] = user_repo
    dp.workflow_data["google_auth_service"] = google_auth_service
    dp.workflow_data["chat_context_service"] = chat_context_service
    dp.workflow_data["chat_rate_limiter"] = chat_rate_limiter

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
        mcp_orchestrator=mcp_orchestrator,
    )
    register_weekly_report_job(
        scheduler=scheduler,
        bot=bot,
        mcp_client=mcp_client,
        openai_service=openai_service,
        user_repo=user_repo,
        mcp_orchestrator=mcp_orchestrator,
    )

    try:
        logger.info("Starting bot polling…")
        await dp.start_polling(bot)
    finally:
        shutdown_scheduler(scheduler)
        if oauth_runner is not None:
            await oauth_runner.cleanup()
        if google_auth_service is not None:
            await google_auth_service.stop()
        await mcp_orchestrator.disconnect_all()
        await close_engine()
        logger.info("Bot stopped.")

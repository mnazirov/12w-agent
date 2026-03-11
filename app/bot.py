"""Bot assembly: Dispatcher, routers, scheduler, lifecycle."""
from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import BOT_TOKEN
from app.handlers import get_all_routers
from app.scheduler import setup_scheduler, shutdown_scheduler
from db.base import close_engine, get_engine

logger = logging.getLogger(__name__)


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
    dp = Dispatcher(storage=MemoryStorage())

    # Register routers
    for router in get_all_routers():
        dp.include_router(router)

    # Setup scheduler (reminders)
    scheduler = setup_scheduler(bot)

    try:
        logger.info("Starting bot polling…")
        await dp.start_polling(bot)
    finally:
        shutdown_scheduler(scheduler)
        await close_engine()
        logger.info("Bot stopped.")

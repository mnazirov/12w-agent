"""Entry point for the 12-Week Year Telegram assistant."""
import asyncio

from app.bot import run_bot

if __name__ == "__main__":
    asyncio.run(run_bot())

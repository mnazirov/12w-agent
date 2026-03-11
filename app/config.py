"""Application configuration loaded from environment variables."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

# --- Telegram ---
BOT_TOKEN: str = os.environ.get("BOT_TOKEN", "")

# --- OpenAI ---
OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL: str = os.environ.get("OPENAI_MODEL", "gpt-5.2")
OPENAI_MAX_TOKENS: int = int(os.environ.get("OPENAI_MAX_TOKENS", "1024"))
OPENAI_TIMEOUT: int = int(os.environ.get("OPENAI_TIMEOUT", "60"))

# --- Database ---
DATABASE_URL: str = os.environ.get("DATABASE_URL", "")

# --- Scheduler / Reminders ---
REMINDER_PLAN_HOUR: int = int(os.environ.get("REMINDER_PLAN_HOUR", "9"))
REMINDER_PLAN_MINUTE: int = int(os.environ.get("REMINDER_PLAN_MINUTE", "0"))
REMINDER_RESULTS_HOUR: int = int(os.environ.get("REMINDER_RESULTS_HOUR", "21"))
REMINDER_RESULTS_MINUTE: int = int(os.environ.get("REMINDER_RESULTS_MINUTE", "0"))
TIMEZONE: str = os.environ.get("TZ", "Europe/Moscow")

# --- Memory / Token budget ---
MEMORY_CONTEXT_MAX_TOKENS: int = int(os.environ.get("MEMORY_CONTEXT_MAX_TOKENS", "500"))
MAX_HISTORY_DAYS: int = int(os.environ.get("MAX_HISTORY_DAYS", "14"))

# --- 12-Week Year defaults ---
TWELVE_WEEKS: int = 12
TOP_N_TASKS: int = 3
MAX_EXTRAS: int = 2

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
CHAT_SESSION_TIMEOUT_MINUTES: int = int(os.environ.get("CHAT_SESSION_TIMEOUT_MINUTES", "120"))
CHAT_RATE_LIMIT_PER_MINUTE: int = int(os.environ.get("CHAT_RATE_LIMIT_PER_MINUTE", "15"))

# --- MCP motivation server ---
MCP_SERVER_URL: str = os.getenv("MCP_SERVER_URL", "http://mcp-server:8001/sse")
GOOGLE_CALENDAR_MCP_URL: str = os.getenv(
    "GOOGLE_CALENDAR_MCP_URL",
    "http://google-calendar-mcp:8002/sse",
)

# --- Google OAuth2 ---
GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI: str = os.getenv("GOOGLE_REDIRECT_URI", "")
GOOGLE_TOKENS_ENCRYPTION_KEY: str = os.getenv("GOOGLE_TOKENS_ENCRYPTION_KEY", "")
OAUTH_CALLBACK_PORT: int = int(os.getenv("OAUTH_CALLBACK_PORT", "8080"))

# --- 12-Week Year defaults ---
TWELVE_WEEKS: int = 12
TOP_N_TASKS: int = 3
MAX_EXTRAS: int = 2

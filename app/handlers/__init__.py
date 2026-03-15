"""Handler routers registry."""
from aiogram import Router

from app.handlers.start import router as start_router
from app.handlers.setup import router as setup_router
from app.handlers.plan import router as plan_router
from app.handlers.checkin import router as checkin_router
from app.handlers.weekly_review import router as weekly_review_router
from app.handlers.status import router as status_router
from app.handlers.report import router as report_router
from app.handlers.google_auth import router as google_auth_router
from app.handlers.chat import router as chat_router


def get_all_routers() -> list[Router]:
    """Return routers in priority order (chat must be last — it's a fallback)."""
    return [
        start_router,
        setup_router,
        plan_router,
        checkin_router,
        weekly_review_router,
        status_router,
        report_router,
        google_auth_router,
        chat_router,
    ]

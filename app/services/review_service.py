"""Weekly review service — scoring, AI reflection, and plan adjustments."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.openai_service import call_structured
from db import repos

logger = logging.getLogger(__name__)


# ── Pydantic models ─────────────────────────────────────────────────────

class WeeklyReviewResponse(BaseModel):
    score_pct: int = 0
    wins: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    adjustments: list[str] = Field(default_factory=list)
    vision_reminder: str = ""
    next_week_focus: str = ""


# ── Public API ───────────────────────────────────────────────────────────

async def weekly_scoring(
    session: AsyncSession,
    user_id: int,
    week_end: date | None = None,
) -> dict[str, int]:
    """Calculate lead-action completion % for the last 7 days.

    Returns: {planned, completed, missed, score_pct}
    """
    end = week_end or date.today()
    start = end - timedelta(days=6)

    stats = await repos.get_weekly_stats(session, user_id, start, end)
    planned = stats["planned"]
    completed = stats["completed"]
    missed = stats["missed"]
    score_pct = (completed * 100 // max(1, planned)) if planned else 0

    return {
        "planned": planned,
        "completed": completed,
        "missed": missed,
        "score_pct": score_pct,
    }


async def generate_review(
    session: AsyncSession,
    user_id: int,
    week_number: int = 0,
    week_end: date | None = None,
) -> WeeklyReviewResponse:
    """Generate an AI-powered weekly review."""
    end = week_end or date.today()
    start = end - timedelta(days=6)

    # Gather context
    vision_row = await repos.get_vision(session, user_id)
    vision_text = vision_row.vision if vision_row else "—"
    why_text = vision_row.why_text if vision_row else "—"

    goals = await repos.get_active_goals(session, user_id)
    goals_text = "\n".join(f"- {g.title}" for g in goals) or "—"

    stats = await weekly_scoring(session, user_id, end)

    # Daily summaries from memory
    memories = await repos.get_recent_memories(session, user_id, limit=7, record_type="daily")
    daily_summaries = "\n".join(
        f"[{m.record_date}] {m.summary}" for m in memories
    ) or "нет данных"

    # Determine week number
    if week_number <= 0:
        wp = await repos.get_current_weekly_plan(session, user_id)
        week_number = wp.week_number if wp else 1

    user_context = f"Неделя {week_number}/12. Цели: {', '.join(g.title for g in goals[:3])}"

    review = await call_structured(
        template_name="weekly_review",
        variables={
            "vision": vision_text,
            "why": why_text,
            "goals": goals_text,
            "week_number": str(week_number),
            "total_planned": str(stats["planned"]),
            "total_completed": str(stats["completed"]),
            "total_missed": str(stats["missed"]),
            "completion_pct": str(stats["score_pct"]),
            "daily_summaries": daily_summaries,
        },
        response_model=WeeklyReviewResponse,
        system_context=user_context,
    )

    return review


def format_review_message(review: WeeklyReviewResponse, stats: dict[str, int]) -> str:
    """Format weekly review as a Telegram message."""
    lines: list[str] = [
        "📊 *Недельный обзор*\n",
        f"*Результат:* {stats['score_pct']}% "
        f"({stats['completed']}/{stats['planned']} задач выполнено)\n",
    ]

    if review.wins:
        lines.append("✅ *Что получилось:*")
        for w in review.wins:
            lines.append(f"• {w}")
        lines.append("")

    if review.improvements:
        lines.append("🔧 *Что улучшить:*")
        for imp in review.improvements:
            lines.append(f"• {imp}")
        lines.append("")

    if review.adjustments:
        lines.append("🔄 *Корректировки:*")
        for adj in review.adjustments:
            lines.append(f"• {adj}")
        lines.append("")

    if review.vision_reminder:
        lines.append(f"🌟 *Напоминание:* {review.vision_reminder}\n")

    if review.next_week_focus:
        lines.append(f"🎯 *Фокус на следующей неделе:* {review.next_week_focus}")

    return "\n".join(lines)

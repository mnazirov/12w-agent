"""Check-in service — evening review with WOOP analysis and reflection."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.openai_service import call_structured
from db import repos

logger = logging.getLogger(__name__)


# ── Pydantic models for AI response validation ──────────────────────────

class WoopItem(BaseModel):
    wish: str = ""
    outcome: str = ""
    obstacle: str = ""
    plan: str = ""


class CheckinAnalysis(BaseModel):
    summary: str = ""
    controllable_factors: list[str] = Field(default_factory=list)
    uncontrollable_factors: list[str] = Field(default_factory=list)
    woop: list[WoopItem] = Field(default_factory=list)
    lesson_prompt: str = ""
    tomorrow_suggestion: str = ""


# ── Public API ───────────────────────────────────────────────────────────

async def analyze_checkin(
    session: AsyncSession,
    user_id: int,
    completed: list[str],
    missed: list[str],
    obstacles_text: str = "",
    today: date | None = None,
) -> CheckinAnalysis:
    """Run AI analysis on the evening check-in and return structured feedback."""
    today = today or date.today()

    # Gather context
    vision_row = await repos.get_vision(session, user_id)
    vision_text = vision_row.vision if vision_row else "—"

    goals = await repos.get_active_goals(session, user_id)
    goals_text = "\n".join(f"- {g.title}" for g in goals) or "—"

    daily_plan = await repos.get_daily_plan(session, user_id, today)
    plan_text = "—"
    if daily_plan and daily_plan.tasks:
        plan_text = "\n".join(
            f"- {t.get('task', t) if isinstance(t, dict) else t}"
            for t in daily_plan.tasks
        )

    completed_text = "\n".join(f"- {c}" for c in completed) or "нет"
    missed_text = "\n".join(f"- {m}" for m in missed) or "нет"

    user_context = f"Цели: {', '.join(g.title for g in goals[:3])}" if goals else ""

    analysis = await call_structured(
        template_name="checkin_evening",
        variables={
            "vision": vision_text,
            "goals": goals_text,
            "todays_plan": plan_text,
            "completed": completed_text,
            "missed": missed_text,
            "obstacles_text": obstacles_text or "не указаны",
        },
        response_model=CheckinAnalysis,
        system_context=user_context,
    )

    return analysis


async def save_checkin(
    session: AsyncSession,
    user_id: int,
    completed: list[str],
    missed: list[str],
    obstacles: list[str] | None = None,
    lesson: str | None = None,
    next_action: str | None = None,
    confidence_score: int | None = None,
    woop_response: dict | None = None,
    checkin_date: date | None = None,
) -> None:
    """Persist the check-in data to the database."""
    checkin_date = checkin_date or date.today()
    await repos.upsert_checkin(
        session,
        user_id=user_id,
        checkin_date=checkin_date,
        completed=completed,
        missed=missed,
        obstacles=obstacles,
        lesson=lesson,
        next_action=next_action,
        confidence_score=confidence_score,
        woop_response=woop_response,
    )


def format_checkin_analysis(analysis: CheckinAnalysis) -> str:
    """Format the check-in analysis as a Telegram message."""
    lines: list[str] = []

    if analysis.summary:
        lines.append(f"📝 {analysis.summary}\n")

    if analysis.controllable_factors:
        lines.append("*Что в твоих силах:*")
        for f in analysis.controllable_factors:
            lines.append(f"• {f}")
        lines.append("")

    if analysis.uncontrollable_factors:
        lines.append("*Что не зависело от тебя:*")
        for f in analysis.uncontrollable_factors:
            lines.append(f"• {f}")
        lines.append("")

    if analysis.woop:
        lines.append("*WOOP-план на завтра:*")
        for w in analysis.woop:
            lines.append(f"🎯 Желание: {w.wish}")
            lines.append(f"   Результат: {w.outcome}")
            lines.append(f"   Препятствие: {w.obstacle}")
            lines.append(f"   План: _{w.plan}_")
            lines.append("")

    if analysis.tomorrow_suggestion:
        lines.append(f"💡 *На завтра:* {analysis.tomorrow_suggestion}")

    return "\n".join(lines)

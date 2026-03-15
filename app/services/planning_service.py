"""Planning service — generates daily plans using AI + 12-Week Year principles."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import MAX_EXTRAS, TOP_N_TASKS
from app.services.openai_service import call_structured
from db import repos

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.services.mcp_orchestrator import MCPOrchestrator


# ── Pydantic models for AI response validation ──────────────────────────

class TaskItem(BaseModel):
    task: str
    implementation_intention: str = ""
    starter_step: str = ""


class ExtraTask(BaseModel):
    task: str


class TimeBlock(BaseModel):
    task: str
    time_slot: str = ""


class DailyPlanResponse(BaseModel):
    top_3: list[TaskItem] = Field(default_factory=list, min_length=1, max_length=5)
    extras: list[ExtraTask] = Field(default_factory=list, max_length=5)
    friction_tip: str = ""
    timeblocks: list[TimeBlock] = Field(default_factory=list)


# ── Public API ───────────────────────────────────────────────────────────

async def generate_daily_plan(
    session: AsyncSession,
    user_id: int,
    today: date | None = None,
    mcp_orchestrator: MCPOrchestrator | None = None,
) -> DailyPlanResponse:
    """Generate (or regenerate) a daily plan for the user.

    Collects context, calls AI, validates, saves to DB, and returns the plan.
    """
    today = today or date.today()

    # Gather context
    vision_row = await repos.get_vision(session, user_id)
    vision_text = vision_row.vision if vision_row else "—"
    why_text = vision_row.why_text if vision_row else "—"

    goals = await repos.get_active_goals(session, user_id)
    goals_text = "\n".join(
        f"- {g.title}" + (f" (метрика: {g.metric})" if g.metric else "")
        for g in goals
    ) or "—"

    weekly_plan = await repos.get_current_weekly_plan(session, user_id)
    lead_actions_text = "\n".join(
        f"- {a}" for a in (weekly_plan.lead_actions if weekly_plan else [])
    ) or "—"

    # Yesterday's missed
    yesterday = today - timedelta(days=1)
    yesterday_checkin = await repos.get_checkin(session, user_id, yesterday)
    missed_text = "\n".join(
        f"- {m}" for m in (yesterday_checkin.missed if yesterday_checkin else [])
    ) or "нет"

    # Memory context
    memories = await repos.get_recent_memories(session, user_id, limit=7)
    memory_text = "\n".join(
        f"[{m.record_date}] {m.summary}" for m in memories
    ) or "—"

    # Sprint info
    sprint = await repos.get_active_sprint(session, user_id)
    if sprint:
        week_num = repos.get_current_week_number(sprint, today)
        days_left = repos.get_sprint_days_remaining(sprint, today)
        sprint_info = f"Неделя {week_num} из 12. Осталось {days_left} дн. до финиша ({sprint.end_date})."
    else:
        sprint_info = "—"

    weekday_names = {
        0: "понедельник", 1: "вторник", 2: "среда", 3: "четверг",
        4: "пятница", 5: "суббота", 6: "воскресенье",
    }
    weekday = weekday_names.get(today.weekday(), "")

    # Build user context for system prompt
    context_parts = [f"Имя: {vision_text[:50]}"]
    if goals:
        context_parts.append(f"Цели: {', '.join(g.title for g in goals[:3])}")
    if sprint:
        context_parts.append(f"Неделя {week_num}/12, осталось {days_left} дн.")
    user_context = ". ".join(context_parts)

    # Call AI
    plan = await call_structured(
        template_name="plan_today",
        variables={
            "vision": vision_text,
            "why": why_text,
            "goals": goals_text,
            "lead_actions": lead_actions_text,
            "yesterday_missed": missed_text,
            "memory": memory_text,
            "sprint_info": sprint_info,
            "today": str(today),
            "weekday": weekday,
        },
        response_model=DailyPlanResponse,
        system_context=user_context,
        mcp_orchestrator=mcp_orchestrator,
        use_tools=bool(mcp_orchestrator),
        tool_server_names=["calendar"],
    )

    # Enforce limits
    plan.top_3 = plan.top_3[:TOP_N_TASKS]
    plan.extras = plan.extras[:MAX_EXTRAS]

    # Save to DB
    all_tasks = [
        {"task": t.task, "implementation_intention": t.implementation_intention,
         "starter_step": t.starter_step}
        for t in plan.top_3
    ] + [{"task": e.task} for e in plan.extras]

    top_3_data = [
        {"task": t.task, "implementation_intention": t.implementation_intention,
         "starter_step": t.starter_step}
        for t in plan.top_3
    ]

    timeblocks_data = [
        {"task": tb.task, "time_slot": tb.time_slot}
        for tb in plan.timeblocks
    ] if plan.timeblocks else None

    await repos.upsert_daily_plan(
        session,
        user_id=user_id,
        plan_date=today,
        tasks=all_tasks,
        top_3=top_3_data,
        timeblocks=timeblocks_data,
        status="active",
    )

    return plan


def format_plan_message(plan: DailyPlanResponse) -> str:
    """Format the plan as a human-readable Telegram message."""
    lines: list[str] = ["📋 *План на сегодня*\n"]

    lines.append("*Топ-3 приоритета:*")
    for i, t in enumerate(plan.top_3, 1):
        lines.append(f"{i}. {t.task}")
        if t.implementation_intention:
            lines.append(f"   _{t.implementation_intention}_")
        if t.starter_step:
            lines.append(f"   🚀 Стартовый шаг: {t.starter_step}")
        lines.append("")

    if plan.extras:
        lines.append("*Дополнительно:*")
        for e in plan.extras:
            lines.append(f"• {e.task}")
        lines.append("")

    if plan.timeblocks:
        lines.append("*Таймблоки:*")
        for tb in plan.timeblocks:
            lines.append(f"🕐 {tb.time_slot} — {tb.task}")
        lines.append("")

    if plan.friction_tip:
        lines.append(f"💡 *Снижение трения:* {plan.friction_tip}")

    return "\n".join(lines)

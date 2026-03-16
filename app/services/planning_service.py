"""Planning service — generates daily plans using AI + 12-Week Year principles."""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import MAX_EXTRAS, TOP_N_TASKS
from app.services.openai_service import call_structured
from db import repos

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.services.mcp_orchestrator import MCPOrchestrator


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


_TRAINING_KEYWORDS = (
    "бег",
    "пробеж",
    "run",
    "running",
    "велосип",
    "cycling",
    "bike",
    "walk",
    "walking",
    "ходьб",
    "прогул",
    "воркаут",
    "турник",
    "outdoor",
    "swim",
    "плаван",
    "поход",
    "hik",
)


def _contains_training_keywords(text: str) -> bool:
    lowered = (text or "").lower()
    return any(word in lowered for word in _TRAINING_KEYWORDS)


def _detect_training_type(goals_text: str) -> str:
    text = (goals_text or "").lower()

    if any(w in text for w in ("бег", "пробеж", "running", "run")):
        return "running"
    if any(w in text for w in ("велосип", "cycling", "bike")):
        return "cycling"
    if any(w in text for w in ("прогул", "ходьб", "walking", "walk")):
        return "walking"
    if any(w in text for w in ("воркаут", "турник", "outdoor_gym")):
        return "outdoor_gym"
    if any(w in text for w in ("плаван", "swim")):
        return "swimming_outdoor"
    if any(w in text for w in ("поход", "hik")):
        return "hiking"

    return "running"


async def _fetch_calendar_context(
    mcp_orchestrator: MCPOrchestrator,
    user_id: int,
    notices: list[str] | None = None,
) -> str | None:
    """Получить события из календаря на сегодня через MCP оркестратор."""
    try:
        today = date.today()
        time_min = datetime.combine(today, time.min, tzinfo=timezone.utc).isoformat()
        time_max = datetime.combine(today, time.max, tzinfo=timezone.utc).isoformat()

        result = await mcp_orchestrator.call_tool(
            tool_name="list_events",
            arguments={
                "calendar_id": "primary",
                "time_min": time_min,
                "time_max": time_max,
            },
            user_id=user_id,
        )

        if isinstance(result, dict) and result.get("requires_auth"):
            if notices is not None:
                notices.append(
                    "Google Calendar не подключён. Подключи аккаунт: /connect_google"
                )
            return None

        if isinstance(result, dict) and result.get("error"):
            error_type = str(result.get("error_type") or "")
            if error_type in {"server_unavailable", "tool_call_failed", "tool_not_found"}:
                return None
            logger.warning("Calendar error while planning: %s", result.get("error"))
            return None

        events = result.get("events", []) if isinstance(result, dict) else []
        if not events:
            return "📅 Календарь: день свободен, встреч нет."

        lines = ["📅 Календарь на сегодня (занятые слоты):"]
        for event in events:
            start = event.get("start", "?")
            end = event.get("end", "?")
            summary = event.get("summary", "Без названия")
            lines.append(f"  • {start}–{end}: {summary}")

        lines.append(
            "\nНе планируй задачи на эти слоты. "
            "Добавляй 15 минут буфера после встреч дольше часа."
        )
        return "\n".join(lines)
    except Exception:
        logger.warning("Calendar unavailable for planning", exc_info=True)
        return None


async def _fetch_weather_context(
    mcp_orchestrator: MCPOrchestrator,
    city: str,
    training_type: str,
    notices: list[str] | None = None,
) -> str | None:
    """Получить прогноз и оценку тренировки через weather MCP."""
    try:
        result = await mcp_orchestrator.call_tool(
            tool_name="get_weather_forecast",
            arguments={
                "city": city,
                "days": 1,
                "training_type": training_type,
            },
        )

        if isinstance(result, dict) and result.get("error"):
            error_text = str(result.get("error") or "")
            error_type = str(result.get("error_type") or "")
            if "не найден" in error_text.lower() and notices is not None:
                notices.append(
                    "Не удалось определить город для погоды. "
                    "Укажи город заново: /plan <город>"
                )
                return None
            if error_type in {"server_unavailable", "tool_call_failed", "tool_not_found"}:
                return None
            if "временно недоступен" in error_text.lower():
                return None
            logger.warning("Weather error while planning: %s", error_text)
            return None

        if not isinstance(result, dict):
            return None

        lines: list[str] = []
        current = result.get("current", {})
        if isinstance(current, dict) and current:
            lines.append(
                f"🌤 Погода в {result.get('city', city)}: "
                f"{current.get('temperature_c', '?')}°C, "
                f"{current.get('description', '')}."
            )

        forecast = result.get("forecast", [])
        if isinstance(forecast, list) and forecast:
            today = forecast[0]
            lines.append(
                f"Прогноз: {today.get('temp_min_c', '?')}°.."
                f"{today.get('temp_max_c', '?')}°C, "
                f"осадки {today.get('precipitation_mm', 0)}мм "
                f"(вероятность {today.get('precipitation_probability_pct', 0)}%), "
                f"ветер до {today.get('wind_max_kmh', 0)} км/ч."
            )

        assessment = result.get("training_assessment")
        if isinstance(assessment, dict):
            if assessment.get("suitable"):
                lines.append(f"\n✅ {assessment.get('recommendation', '')}")
            else:
                lines.append(
                    f"\n⛔ {assessment.get('recommendation', '')}\n"
                    f"Альтернатива: {assessment.get('alternative', 'тренировка в помещении')}."
                )

        return "\n".join(lines) if lines else None
    except Exception:
        logger.warning("Weather unavailable for planning", exc_info=True)
        return None


async def _gather_day_context(
    *,
    user_id: int,
    city: str | None,
    has_training_goals: bool,
    training_type: str,
    mcp_orchestrator: MCPOrchestrator | None,
    notices: list[str] | None = None,
) -> str:
    """Собрать текстовый контекст дня для включения в planning prompt."""
    if mcp_orchestrator is None:
        return ""

    parts: list[str] = []

    calendar_context = await _fetch_calendar_context(
        mcp_orchestrator,
        user_id=user_id,
        notices=notices,
    )
    if calendar_context:
        parts.append(calendar_context)

    if city and has_training_goals:
        weather_context = await _fetch_weather_context(
            mcp_orchestrator,
            city=city,
            training_type=training_type,
            notices=notices,
        )
        if weather_context:
            parts.append(weather_context)

    return "\n\n".join(parts) if parts else ""


async def generate_daily_plan(
    session: AsyncSession,
    user_id: int,
    today: date | None = None,
    mcp_orchestrator: MCPOrchestrator | None = None,
    city_override: str | None = None,
    notices: list[str] | None = None,
) -> DailyPlanResponse:
    """Generate (or regenerate) a daily plan for the user."""
    today = today or date.today()

    vision_row = await repos.get_vision(session, user_id)
    vision_text = vision_row.vision if vision_row else "—"
    why_text = vision_row.why_text if vision_row else "—"

    goals = await repos.get_active_goals(session, user_id)
    goals_text = "\n".join(
        f"- {goal.title}" + (f" (метрика: {goal.metric})" if goal.metric else "")
        for goal in goals
    ) or "—"

    weekly_plan = await repos.get_current_weekly_plan(session, user_id)
    lead_actions = weekly_plan.lead_actions if weekly_plan else []
    lead_actions_text = "\n".join(f"- {action}" for action in lead_actions) or "—"

    yesterday = today - timedelta(days=1)
    yesterday_checkin = await repos.get_checkin(session, user_id, yesterday)
    missed_text = "\n".join(
        f"- {item}" for item in (yesterday_checkin.missed if yesterday_checkin else [])
    ) or "нет"

    memories = await repos.get_recent_memories(session, user_id, limit=7)
    memory_text = "\n".join(f"[{m.record_date}] {m.summary}" for m in memories) or "—"

    sprint = await repos.get_active_sprint(session, user_id)
    if sprint:
        week_num = repos.get_current_week_number(sprint, today)
        days_left = repos.get_sprint_days_remaining(sprint, today)
        sprint_info = (
            f"Неделя {week_num} из 12. Осталось {days_left} дн. "
            f"до финиша ({sprint.end_date})."
        )
    else:
        sprint_info = "—"

    weekday_names = {
        0: "понедельник",
        1: "вторник",
        2: "среда",
        3: "четверг",
        4: "пятница",
        5: "суббота",
        6: "воскресенье",
    }
    weekday = weekday_names.get(today.weekday(), "")

    context_parts = [f"Имя: {vision_text[:50]}"]
    if goals:
        context_parts.append(f"Цели: {', '.join(g.title for g in goals[:3])}")
    if sprint:
        context_parts.append(f"Неделя {week_num}/12, осталось {days_left} дн.")
    user_context = ". ".join(context_parts)

    city = (city_override or "").strip() or await repos.get_user_city(session, user_id)

    combined_goals = f"{goals_text}\n{lead_actions_text}"
    has_training_goals = _contains_training_keywords(combined_goals)
    training_type = _detect_training_type(combined_goals)

    day_context = await _gather_day_context(
        user_id=user_id,
        city=city,
        has_training_goals=has_training_goals,
        training_type=training_type,
        mcp_orchestrator=mcp_orchestrator,
        notices=notices,
    )

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
            "day_context": day_context or "",
        },
        response_model=DailyPlanResponse,
        system_context=user_context,
        mcp_orchestrator=mcp_orchestrator,
        use_tools=False,
        user_id=user_id,
    )

    plan.top_3 = plan.top_3[:TOP_N_TASKS]
    plan.extras = plan.extras[:MAX_EXTRAS]

    all_tasks = [
        {
            "task": item.task,
            "implementation_intention": item.implementation_intention,
            "starter_step": item.starter_step,
        }
        for item in plan.top_3
    ] + [{"task": item.task} for item in plan.extras]

    top_3_data = [
        {
            "task": item.task,
            "implementation_intention": item.implementation_intention,
            "starter_step": item.starter_step,
        }
        for item in plan.top_3
    ]

    timeblocks_data = [
        {"task": block.task, "time_slot": block.time_slot}
        for block in plan.timeblocks
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
    for i, task in enumerate(plan.top_3, 1):
        lines.append(f"{i}. {task.task}")
        if task.implementation_intention:
            lines.append(f"   _{task.implementation_intention}_")
        if task.starter_step:
            lines.append(f"   🚀 Стартовый шаг: {task.starter_step}")
        lines.append("")

    if plan.extras:
        lines.append("*Дополнительно:*")
        for extra in plan.extras:
            lines.append(f"• {extra.task}")
        lines.append("")

    if plan.timeblocks:
        lines.append("*Таймблоки:*")
        for block in plan.timeblocks:
            lines.append(f"🕐 {block.time_slot} — {block.task}")
        lines.append("")

    if plan.friction_tip:
        lines.append(f"💡 *Снижение трения:* {plan.friction_tip}")

    return "\n".join(lines)

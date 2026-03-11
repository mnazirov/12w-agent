"""Memory service — summarizes daily/weekly data into compact records for prompt context."""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import MAX_HISTORY_DAYS, MEMORY_CONTEXT_MAX_TOKENS
from app.services.openai_service import call_text
from db import repos

logger = logging.getLogger(__name__)

# Rough estimate: 1 token ≈ 4 chars for Russian/English mix
_CHARS_PER_TOKEN = 4


async def summarize_day(
    session: AsyncSession,
    user_id: int,
    target_date: date | None = None,
) -> str:
    """Compress today's plan + check-in into 2–3 sentences and store as memory record."""
    target_date = target_date or date.today()

    # Gather data
    plan = await repos.get_daily_plan(session, user_id, target_date)
    checkin = await repos.get_checkin(session, user_id, target_date)

    if not plan and not checkin:
        return ""

    parts: list[str] = [f"Дата: {target_date}."]
    if plan and plan.tasks:
        task_names = [
            t.get("task", t) if isinstance(t, dict) else str(t)
            for t in plan.tasks
        ]
        parts.append(f"Запланировано: {', '.join(task_names)}.")
    if checkin:
        if checkin.completed:
            parts.append(f"Выполнено: {', '.join(checkin.completed)}.")
        if checkin.missed:
            parts.append(f"Не сделано: {', '.join(checkin.missed)}.")
        if checkin.lesson:
            parts.append(f"Урок: {checkin.lesson}.")

    raw_context = " ".join(parts)

    # If short enough, skip AI summarization
    if len(raw_context) < 300:
        summary = raw_context
    else:
        try:
            summary = await call_text(
                user_message=(
                    f"Сожми следующее в 2–3 предложения для будущего контекста. "
                    f"Сохрани ключевые факты и уроки:\n\n{raw_context}"
                ),
                system_context="Ты помощник для сжатия ежедневных записей. Пиши кратко.",
            )
            summary = summary.strip()
            if not summary:
                summary = raw_context[:300]
        except Exception as e:
            logger.warning("AI summarization failed, using raw: %s", e)
            summary = raw_context[:300]

    # Save memory record
    await repos.save_memory_record(
        session,
        user_id=user_id,
        record_date=target_date,
        summary=summary,
        record_type="daily",
    )
    logger.info("Saved daily memory for user %d, date %s", user_id, target_date)
    return summary


async def get_context(
    session: AsyncSession,
    user_id: int,
    max_tokens: int | None = None,
) -> str:
    """Assemble recent memory records into a context string within token budget."""
    budget = max_tokens or MEMORY_CONTEXT_MAX_TOKENS
    max_chars = budget * _CHARS_PER_TOKEN

    memories = await repos.get_recent_memories(
        session, user_id, limit=MAX_HISTORY_DAYS
    )

    if not memories:
        return ""

    result_parts: list[str] = []
    total_chars = 0
    for m in memories:
        line = f"[{m.record_date}] {m.summary}"
        if total_chars + len(line) > max_chars:
            break
        result_parts.append(line)
        total_chars += len(line)

    return "\n".join(result_parts)

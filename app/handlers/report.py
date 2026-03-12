"""
/report — аналитический отчёт за неделю (MCP pipeline + AI insights).
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.services.mcp_client import MCPMotivationClient
from app.services.pipeline_service import run_analytics_pipeline

router = Router(name="report")

_ACTION_LABELS = {
    "plan": "📋 Планы",
    "checkin": "✅ Чек-ины",
    "review": "📊 Обзоры",
    "setup": "⚙️ Настройки",
}

_PEAK_TIME_TEXT = {
    "morning_6_12": "🌅 Утро (6–12)",
    "afternoon_12_18": "☀️ День (12–18)",
    "evening_18_24": "🌙 Вечер (18–24)",
    "night_0_6": "🦉 Ночь (0–6)",
}

_RECOMMENDATION_TEXT = {
    "no_plans_at_all": "⚠️ За неделю ни одного плана — начни с /plan",
    "low_plan_frequency": "📋 Планы реже чем в половине дней — попробуй чаще",
    "no_checkins_at_all": "⚠️ Ни одного чек-ина — /checkin займёт 1 минуту",
    "plans_without_checkins": "📝 Планы есть, чек-инов мало — рефлексия закрепляет прогресс",
    "too_many_missed_days": "📅 Больше половины дней пропущено — пересмотри цели /setup",
    "consecutive_missed_days": "🔴 Несколько дней подряд пропущено",
    "strong_performance": "🏆 Отличная неделя!",
    "moderate_performance": "👍 Неплохо, фокус на регулярности",
    "needs_attention": "🎯 Слабая неделя — начни заново с /plan",
}


@router.message(Command("report"))
async def cmd_report(
    message: Message,
    mcp_client: MCPMotivationClient,
    openai_service=None,
    user_repo=None,
):
    """Run the full analytics pipeline and display the report."""
    uid = message.from_user.id
    await message.answer("📊 Формирую аналитический отчёт...")

    # Get vision for AI context
    vision = None
    if user_repo:
        try:
            v = await user_repo.get_vision(uid)
            if v:
                vision = getattr(v, "vision", None)
        except Exception:
            pass

    result = await run_analytics_pipeline(
        mcp_client=mcp_client,
        openai_service=openai_service,
        user_id=uid,
        days=7,
        vision=vision,
    )

    if not result.get("success"):
        error = result.get("error", "Неизвестная ошибка")
        await message.answer(f"⚠️ Не удалось сформировать отчёт: {error}")
        return

    # ── Format report ──────────────────────────────────────────
    score = result.get("completion_score", 0)
    score_bar = "█" * int(score * 10) + "░" * (10 - int(score * 10))

    real = result.get("real_actions_breakdown", {})
    streak = result.get("current_streak", 0)
    longest = result.get("longest_streak", 0)
    active = result.get("active_days", 0)
    missed = result.get("missed_days", 0)
    period = result.get("period_days", 7)
    best = result.get("best_day", {})

    lines = [
        "📊 <b>Аналитический отчёт за 7 дней</b>",
        "",
        f"Выполнение: {score_bar} {score:.0%}",
    ]

    # Comparison with previous week
    prev = result.get("previous_week")
    if prev and prev.get("completion_score") is not None:
        prev_score = prev["completion_score"]
        if isinstance(prev_score, (int, float)):
            diff = score - prev_score
            if diff > 0.05:
                lines.append(f"📈 +{diff:.0%} к прошлой неделе")
            elif diff < -0.05:
                lines.append(f"📉 {diff:.0%} к прошлой неделе")
            else:
                lines.append("➡️ На уровне прошлой недели")

    lines += ["", "<b>Действия:</b>"]
    for action in ("plan", "checkin", "review", "setup"):
        count = real.get(action, 0)
        label = _ACTION_LABELS.get(action, action)
        lines.append(f"  {label}: {count}")

    lines += [
        "",
        f"📅 Активных дней: {active}/{period}",
        f"🔥 Серия: {streak} дн. (рекорд: {longest})",
    ]

    if best.get("date") and best.get("score", 0) > 0:
        lines.append(f"⭐ Лучший день: {best['date']} ({best['score']} действий)")

    peak = result.get("peak_time_block")
    if peak:
        peak_text = _PEAK_TIME_TEXT.get(peak)
        if peak_text:
            lines.append(f"⏰ Пик активности: {peak_text}")

    # AI insights
    ai_insights = result.get("ai_insights")
    if ai_insights:
        lines += ["", "<b>💡 AI-анализ:</b>", ai_insights]

    # Recommendations
    recs = result.get("recommendations", [])
    rec_lines = []
    for r in recs:
        if r in _RECOMMENDATION_TEXT:
            rec_lines.append(_RECOMMENDATION_TEXT[r])
    if rec_lines:
        lines += ["", "<b>Рекомендации:</b>"]
        lines += rec_lines

    # Pipeline metadata
    pipeline = result.get("pipeline", {})
    steps = pipeline.get("steps", [])
    if steps:
        lines += [
            "",
            f"<i>🔗 Пайплайн: {len(steps)} шагов "
            f"({' → '.join(steps)})</i>",
        ]

    snapshot_id = result.get("snapshot_id")
    if snapshot_id:
        lines.append(f"<i>💾 Отчёт #{snapshot_id}</i>")

    text = "\n".join(lines)
    try:
        await message.answer(text, parse_mode="HTML")
    except Exception:
        await message.answer(text)

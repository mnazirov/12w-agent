"""Handlers for motivation settings and achievements summary commands."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.services.mcp_client import MCPMotivationClient

logger = logging.getLogger(__name__)
router = Router(name="motivation")

_INTERVALS = [2, 4, 8, 12, 24]
_STYLES = {
    "gentle": "🌿 Мягкий",
    "balanced": "⚖️ Баланс",
    "intense": "🔥 Жёсткий",
}
_ENGAGEMENT_EMOJI = {
    "highly_active": "🟢 Высокий",
    "active": "🟡 Хороший",
    "moderate": "🟠 Умеренный",
    "declining": "🔴 Снижается",
    "inactive": "⚫ Неактивен",
    "new_user": "🆕 Новый",
}
_TREND_EMOJI = {
    "improving": "📈 Рост",
    "stable": "➡️ Стабильно",
    "declining": "📉 Спад",
    "new": "🆕 Начало",
}


class MotivationSettings(StatesGroup):
    """FSM states for motivation settings."""

    waiting_for_interval = State()


def _format_interval(minutes: float) -> str:
    """Форматирует интервал в человекочитаемый вид."""
    value = float(minutes)

    if value >= 60:
        h = value / 60
        if abs(h - round(h)) < 1e-6:
            return f"{int(round(h))}ч"
        whole_h = int(h)
        remaining_m = int(round(value - whole_h * 60))
        if remaining_m == 60:
            whole_h += 1
            remaining_m = 0
        if remaining_m == 0:
            return f"{whole_h}ч"
        return f"{whole_h}ч {remaining_m}мин"

    if abs(value - round(value)) < 1e-6:
        return f"{int(round(value))}мин"
    return f"{value:.2f}".rstrip("0").rstrip(".") + "мин"


def _build_settings_text(cfg: dict) -> str:
    """Build HTML text for motivation settings card."""
    enabled = bool(cfg.get("enabled", 1))
    interval = float(cfg.get("interval_hours", 8))
    style_key = str(cfg.get("style", "balanced"))
    style_label = _STYLES.get(style_key, style_key)
    quiet_start = int(cfg.get("quiet_start", 23))
    quiet_end = int(cfg.get("quiet_end", 7))

    status = "✅ Включена" if enabled else "❌ Выключена"
    return (
        "🔔 <b>Настройки мотивации</b>\n\n"
        f"Статус: {status}\n"
        f"⏰ Интервал: каждые <b>{_format_interval(interval * 60)}</b>\n"
        f"🎨 Стиль: {style_label}\n"
        f"🌙 Тихие часы: {quiet_start:02d}:00 — {quiet_end:02d}:00"
    )


def _build_settings_kb(cfg: dict) -> InlineKeyboardBuilder:
    """Build inline keyboard for motivation settings."""
    enabled = bool(cfg.get("enabled", 1))
    current_interval = float(cfg.get("interval_hours", 8.0))
    current_style = str(cfg.get("style", "balanced"))

    kb = InlineKeyboardBuilder()

    if enabled:
        kb.button(text="❌ Выключить", callback_data="motiv:toggle:0")
    else:
        kb.button(text="✅ Включить", callback_data="motiv:toggle:1")

    for hours in _INTERVALS:
        mark = "✅ " if abs(current_interval - float(hours)) < 0.001 else ""
        kb.button(text=f"{mark}{hours}ч", callback_data=f"motiv:int:{hours}")

    kb.row(InlineKeyboardButton(text="✏️ Ввести в минутах", callback_data="motiv:int:custom"))

    for key, label in _STYLES.items():
        mark = "✅ " if current_style == key else ""
        kb.button(text=f"{mark}{label}", callback_data=f"motiv:style:{key}")

    kb.adjust(1, len(_INTERVALS), 1, len(_STYLES))
    return kb


@router.message(Command("motivation"))
async def cmd_motivation(message: Message, mcp_client: MCPMotivationClient) -> None:
    """Show motivation settings panel."""
    if not message.from_user:
        return

    cfg = await mcp_client.get_motivation_config(message.from_user.id)
    if "error" in cfg:
        await message.answer("⚠️ Сервис мотивации недоступен")
        return

    await message.answer(
        _build_settings_text(cfg),
        reply_markup=_build_settings_kb(cfg).as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("motiv:"))
async def cb_motivation(
    callback: CallbackQuery,
    mcp_client: MCPMotivationClient,
    state: FSMContext,
) -> None:
    """Handle motivation settings updates from inline buttons."""
    if not callback.from_user:
        await callback.answer()
        return

    payload = (callback.data or "").split(":")
    if len(payload) != 3:
        await callback.answer("⚠️ Некорректная команда", show_alert=False)
        return

    _, kind, val = payload
    uid = callback.from_user.id

    try:
        if kind == "toggle":
            await mcp_client.update_motivation_config(uid, enabled=(val == "1"))
        elif kind == "int":
            if val == "custom":
                await state.set_state(MotivationSettings.waiting_for_interval)
                if callback.message:
                    await callback.message.edit_text(
                        "⏰ <b>Введите интервал в минутах</b>\n\n"
                        "Отправьте число от 1 до 2880 (48 часов).\n"
                        "Например: <code>30</code>, <code>90</code>, <code>360</code>\n\n"
                        "Для отмены отправьте /motivation",
                        parse_mode="HTML",
                    )
                await callback.answer()
                return
            await mcp_client.update_motivation_config(uid, interval_hours=float(val))
        elif kind == "style":
            await mcp_client.update_motivation_config(uid, style=val)
    except Exception as exc:
        logger.debug("Failed to apply motivation setting for %s: %s", uid, exc)

    cfg = await mcp_client.get_motivation_config(uid)
    if "error" in cfg:
        await callback.answer("⚠️ Сервис мотивации недоступен", show_alert=False)
        return

    if callback.message:
        await callback.message.edit_text(
            _build_settings_text(cfg),
            reply_markup=_build_settings_kb(cfg).as_markup(),
            parse_mode="HTML",
        )
    await callback.answer("✅ Сохранено")


@router.message(MotivationSettings.waiting_for_interval)
async def process_custom_interval(message: Message, mcp_client: MCPMotivationClient, state: FSMContext):
    """Обработка ручного ввода интервала мотивации в минутах."""
    text = (message.text or "").strip().replace(",", ".")

    # Проверка команды отмены
    if text.startswith("/"):
        await state.clear()
        return

    # Валидация
    try:
        minutes = float(text)
    except ValueError:
        await message.answer(
            "❌ Не удалось распознать число.\n"
            "Отправьте количество минут от 1 до 2880, например: <code>30</code> или <code>90</code>",
            parse_mode="HTML",
        )
        return

    if minutes < 1 or minutes > 2880:
        await message.answer(
            "❌ Интервал должен быть от <b>1</b> до <b>2880</b> минут (48 часов).\n"
            "Попробуйте ещё раз:",
            parse_mode="HTML",
        )
        return

    # Конвертация в часы для MCP
    hours = minutes / 60.0

    # Сохраняем
    uid = message.from_user.id
    await mcp_client.update_motivation_config(uid, interval_hours=hours)
    await state.clear()

    # Показываем обновлённые настройки
    cfg = await mcp_client.get_motivation_config(uid)
    if "error" in cfg:
        await message.answer("✅ Интервал сохранён, но не удалось загрузить настройки.")
        return

    # Человекочитаемый формат
    display = _format_interval(minutes)

    kb = _build_settings_kb(cfg)
    await message.answer(
        f"✅ Интервал установлен: <b>{display}</b>\n\n" + _build_settings_text(cfg),
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.message(Command("achievements"))
async def cmd_achievements(message: Message, mcp_client: MCPMotivationClient) -> None:
    """Show 7-day achievements and engagement summary."""
    if not message.from_user:
        return

    uid = message.from_user.id
    report = await mcp_client.get_achievement_report(uid, 7)
    engagement = await mcp_client.check_engagement(uid)

    if "error" in report or "error" in engagement:
        await message.answer("⚠️ Сервис мотивации недоступен")
        return

    breakdown = report.get("breakdown", {}) if isinstance(report, dict) else {}
    plans = int(breakdown.get("plan", 0))
    checkins = int(breakdown.get("checkin", 0))
    reviews = int(breakdown.get("review", 0))
    chat = int(breakdown.get("chat", 0))
    total = int(report.get("total_activities", 0))

    current_streak = int(report.get("current_streak", 0))
    longest_streak = int(report.get("longest_streak", 0))
    consistency = int(round(float(report.get("consistency", 0)) * 100))
    trend = _TREND_EMOJI.get(str(report.get("trend", "stable")), "➡️ Стабильно")

    level_key = str(engagement.get("engagement_level", "new_user"))
    level = _ENGAGEMENT_EMOJI.get(level_key, "🆕 Новый")
    hours = engagement.get("hours_inactive")
    last_activity = "нет данных" if hours is None else f"{hours}ч назад"

    text = (
        "📊 <b>Достижения за 7 дней</b>\n\n"
        f"📝 Планы: {plans}\n"
        f"✅ Чек-ины: {checkins}\n"
        f"📋 Обзоры: {reviews}\n"
        f"💬 AI-чат: {chat}\n"
        f"📌 Всего действий: {total}\n\n"
        f"🔥 Серия: <b>{current_streak} дн.</b> (рекорд: {longest_streak})\n"
        f"📅 Стабильность: {consistency}%\n"
        f"📈 Тренд: {trend}\n\n"
        f"🎯 Вовлечённость: {level}\n"
        f"🕐 Последняя активность: {last_activity}"
    )
    await message.answer(text, parse_mode="HTML")

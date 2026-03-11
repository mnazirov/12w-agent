"""Inline keyboard builders for Telegram UX."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


# ── Main menu (after /start) ────────────────────────────────────────────

def main_menu_kb(has_active_sprint: bool = True) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if has_active_sprint:
        rows.append([
            InlineKeyboardButton(text="📋 План на сегодня", callback_data="cmd_plan"),
            InlineKeyboardButton(text="📝 Вечерний чек-ин", callback_data="cmd_checkin"),
        ])
        rows.append([
            InlineKeyboardButton(text="📊 Статус", callback_data="cmd_status"),
            InlineKeyboardButton(text="🔄 Недельный обзор", callback_data="cmd_weekly_review"),
        ])
        rows.append([
            InlineKeyboardButton(text="🎯 Настроить цели", callback_data="cmd_setup"),
        ])
    else:
        rows.append([
            InlineKeyboardButton(text="🚀 Начать 12-недельный марафон", callback_data="cmd_setup"),
        ])
        rows.append([
            InlineKeyboardButton(text="📊 Статус", callback_data="cmd_status"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── Setup: confirm / edit ───────────────────────────────────────────────

def setup_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Сохранить", callback_data="setup_save"),
            InlineKeyboardButton(text="✏️ Изменить", callback_data="setup_edit"),
        ],
    ])


# ── Plan: accept / regenerate ───────────────────────────────────────────

def plan_action_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Принять план", callback_data="plan_accept"),
            InlineKeyboardButton(text="🔄 Другой план", callback_data="plan_regenerate"),
        ],
    ])


# ── Checkin: task status buttons ────────────────────────────────────────

def checkin_tasks_kb(tasks: list[str], done_indices: set[int] | None = None) -> InlineKeyboardMarkup:
    """Build a keyboard with toggle buttons for each task (done/skip)."""
    done_indices = done_indices or set()
    rows: list[list[InlineKeyboardButton]] = []
    for i, task in enumerate(tasks):
        short = task[:40] + ("…" if len(task) > 40 else "")
        if i in done_indices:
            label = f"✅ {short}"
        else:
            label = f"⬜ {short}"
        rows.append([
            InlineKeyboardButton(text=label, callback_data=f"ci_toggle_{i}"),
        ])
    rows.append([
        InlineKeyboardButton(text="📤 Отправить", callback_data="ci_submit"),
    ])
    return rows_to_kb(rows)


def rows_to_kb(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── Checkin: confidence score ───────────────────────────────────────────

def confidence_kb() -> InlineKeyboardMarkup:
    """1–10 confidence score buttons in two rows."""
    row1 = [
        InlineKeyboardButton(text=str(i), callback_data=f"ci_conf_{i}")
        for i in range(1, 6)
    ]
    row2 = [
        InlineKeyboardButton(text=str(i), callback_data=f"ci_conf_{i}")
        for i in range(6, 11)
    ]
    return InlineKeyboardMarkup(inline_keyboard=[row1, row2])


# ── Skip button ─────────────────────────────────────────────────────────

def skip_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Пропустить", callback_data="skip")],
    ])

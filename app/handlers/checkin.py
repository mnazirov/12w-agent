"""Handler for /checkin — evening check-in FSM with WOOP and reflection."""
from __future__ import annotations

import logging
from datetime import date

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.keyboards import checkin_tasks_kb, confidence_kb, skip_kb
from app.services.checkin_service import (
    analyze_checkin,
    format_checkin_analysis,
    save_checkin,
)
from app.services.memory_service import summarize_day
from app.states import CheckinStates
from db.base import get_session_factory
from db.repos import get_daily_plan, get_or_create_user

logger = logging.getLogger(__name__)
router = Router(name="checkin")


@router.message(Command("checkin"))
async def cmd_checkin(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return

    async with get_session_factory()() as session:
        user = await get_or_create_user(
            session, message.from_user.id, message.from_user.first_name
        )
        plan = await get_daily_plan(session, user.id, date.today())

    if not plan or not plan.tasks:
        await message.answer(
            "На сегодня плана нет. Сначала составь: /plan"
        )
        return

    # Extract task names
    tasks: list[str] = []
    for t in plan.tasks:
        if isinstance(t, dict):
            tasks.append(t.get("task", str(t)))
        else:
            tasks.append(str(t))

    await state.clear()
    await state.update_data(tasks=tasks, done=set())
    await state.set_state(CheckinStates.mark_done)

    await message.answer(
        "📝 *Вечерний чек-ин*\n\n"
        "Отметь выполненные задачи (нажми — переключится).\n"
        "Когда всё отмечено — нажми «Отправить».",
        reply_markup=checkin_tasks_kb(tasks),
        parse_mode="Markdown",
    )


# ── Toggle task done/undone ──────────────────────────────────────────────

@router.callback_query(CheckinStates.mark_done, F.data.startswith("ci_toggle_"))
async def cb_toggle_task(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    idx = int(callback.data.split("_")[-1])  # type: ignore[union-attr]

    data = await state.get_data()
    done: set[int] = set(data.get("done", set()))
    if idx in done:
        done.discard(idx)
    else:
        done.add(idx)
    await state.update_data(done=done)

    tasks: list[str] = data["tasks"]
    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=checkin_tasks_kb(tasks, done)
        )


# ── Submit task marks ────────────────────────────────────────────────────

@router.callback_query(CheckinStates.mark_done, F.data == "ci_submit")
async def cb_submit_marks(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    tasks: list[str] = data["tasks"]
    done: set[int] = set(data.get("done", set()))

    completed = [tasks[i] for i in sorted(done) if i < len(tasks)]
    missed = [tasks[i] for i in range(len(tasks)) if i not in done]

    await state.update_data(completed=completed, missed=missed)

    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)

    if missed:
        await state.set_state(CheckinStates.obstacles)
        missed_text = "\n".join(f"• {m}" for m in missed)
        msg = (
            f"Не сделано:\n{missed_text}\n\n"
            "Что помешало? Напиши кратко (или пропусти)."
        )
        if callback.message:
            await callback.message.answer(msg, reply_markup=skip_kb())
    else:
        # All done — skip obstacles, go to lesson
        await state.set_state(CheckinStates.lesson)
        if callback.message:
            await callback.message.answer(
                "🎉 Все задачи выполнены!\n\n"
                "Какой урок из сегодняшнего дня? (или пропусти)",
                reply_markup=skip_kb(),
            )


# ── Obstacles ────────────────────────────────────────────────────────────

@router.message(CheckinStates.obstacles)
async def on_obstacles(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    await state.update_data(obstacles_text=text)
    await state.set_state(CheckinStates.lesson)
    await message.answer(
        "Какой урок из сегодняшнего дня?\n"
        "Что ты узнал о себе? (или пропусти)",
        reply_markup=skip_kb(),
    )


@router.callback_query(CheckinStates.obstacles, F.data == "skip")
async def cb_skip_obstacles(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(obstacles_text="")
    await state.set_state(CheckinStates.lesson)
    if callback.message:
        await callback.message.answer(
            "Какой урок из сегодняшнего дня? (или пропусти)",
            reply_markup=skip_kb(),
        )


# ── Lesson ───────────────────────────────────────────────────────────────

@router.message(CheckinStates.lesson)
async def on_lesson(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    await state.update_data(lesson=text)
    await state.set_state(CheckinStates.confidence)
    await message.answer(
        "Оцени уверенность в завтрашнем дне от 1 до 10:",
        reply_markup=confidence_kb(),
    )


@router.callback_query(CheckinStates.lesson, F.data == "skip")
async def cb_skip_lesson(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(lesson="")
    await state.set_state(CheckinStates.confidence)
    if callback.message:
        await callback.message.answer(
            "Оцени уверенность в завтрашнем дне от 1 до 10:",
            reply_markup=confidence_kb(),
        )


# ── Confidence score → finalize ──────────────────────────────────────────

@router.callback_query(CheckinStates.confidence, F.data.startswith("ci_conf_"))
async def cb_confidence(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    score = int(callback.data.split("_")[-1])  # type: ignore[union-attr]

    data = await state.get_data()
    completed: list[str] = data.get("completed", [])
    missed: list[str] = data.get("missed", [])
    obstacles_text: str = data.get("obstacles_text", "")
    lesson: str = data.get("lesson", "")

    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer("⏳ Анализирую результаты…")

    # AI analysis (WOOP, attribution, etc.)
    analysis = None
    woop_dict = None
    if missed:
        try:
            async with get_session_factory()() as session:
                user = await get_or_create_user(
                    session, callback.from_user.id, callback.from_user.first_name  # type: ignore[union-attr]
                )
                analysis = await analyze_checkin(
                    session, user.id, completed, missed, obstacles_text
                )
        except Exception as e:
            logger.exception("Checkin analysis failed: %s", e)

        if analysis and analysis.woop:
            woop_dict = {
                "items": [w.model_dump() for w in analysis.woop],
            }

    # Save to DB + memory
    try:
        async with get_session_factory()() as session:
            user = await get_or_create_user(
                session, callback.from_user.id, callback.from_user.first_name  # type: ignore[union-attr]
            )
            next_action = analysis.tomorrow_suggestion if analysis else None
            await save_checkin(
                session,
                user_id=user.id,
                completed=completed,
                missed=missed,
                obstacles=[obstacles_text] if obstacles_text else None,
                lesson=lesson or None,
                next_action=next_action,
                confidence_score=score,
                woop_response=woop_dict,
            )
            # Summarize day for memory
            await summarize_day(session, user.id)
            await session.commit()
    except Exception as e:
        logger.exception("Failed to save checkin: %s", e)

    await state.clear()

    # Send results
    parts: list[str] = [f"✅ Чек-ин сохранён! Уверенность: {score}/10\n"]
    if analysis:
        parts.append(format_checkin_analysis(analysis))
    if analysis and analysis.lesson_prompt:
        parts.append(f"\n🤔 _{analysis.lesson_prompt}_")

    if callback.message:
        await callback.message.answer(
            "\n".join(parts),
            parse_mode="Markdown",
        )

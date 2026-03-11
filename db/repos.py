"""Async repository functions (CRUD) for all domain models."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Checkin,
    DailyPlan,
    Goal12W,
    MemoryRecord,
    Sprint,
    User,
    VisionAndWhy,
    WeeklyPlan,
)

logger = logging.getLogger(__name__)


# =========================================================================
# Users
# =========================================================================

async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    first_name: str | None = None,
) -> User:
    """Return existing user or create a new one."""
    stmt = select(User).where(User.telegram_id == telegram_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if user is not None:
        if first_name and user.first_name != first_name:
            user.first_name = first_name
            await session.flush()
        return user
    user = User(telegram_id=telegram_id, first_name=first_name)
    session.add(user)
    await session.flush()
    return user


async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()


async def get_all_telegram_ids(session: AsyncSession) -> list[int]:
    result = await session.execute(select(User.telegram_id))
    return list(result.scalars().all())


# =========================================================================
# Vision & Why
# =========================================================================

async def upsert_vision(
    session: AsyncSession,
    user_id: int,
    vision: str,
    why_text: str,
    values: str | None = None,
) -> VisionAndWhy:
    """Create or update vision_and_why for user."""
    stmt = select(VisionAndWhy).where(VisionAndWhy.user_id == user_id)
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is not None:
        row.vision = vision
        row.why_text = why_text
        row.values = values
        await session.flush()
        return row
    row = VisionAndWhy(user_id=user_id, vision=vision, why_text=why_text, values=values)
    session.add(row)
    await session.flush()
    return row


async def get_vision(session: AsyncSession, user_id: int) -> VisionAndWhy | None:
    result = await session.execute(
        select(VisionAndWhy).where(VisionAndWhy.user_id == user_id)
    )
    return result.scalar_one_or_none()


# =========================================================================
# Goals 12W
# =========================================================================

async def add_goals(
    session: AsyncSession,
    user_id: int,
    goals: list[dict[str, Any]],
    deadline: date | None = None,
) -> list[Goal12W]:
    """Add multiple goals. Each dict should have at least 'title'."""
    dl = deadline or (date.today() + timedelta(weeks=12))
    created: list[Goal12W] = []
    for g in goals:
        goal = Goal12W(
            user_id=user_id,
            title=g.get("title", g.get("text", "")),
            metric=g.get("metric"),
            baseline=g.get("baseline"),
            target=g.get("target"),
            deadline=dl,
            importance=g.get("importance"),
            is_active=True,
        )
        session.add(goal)
        created.append(goal)
    await session.flush()
    return created


async def get_active_goals(session: AsyncSession, user_id: int) -> Sequence[Goal12W]:
    result = await session.execute(
        select(Goal12W)
        .where(Goal12W.user_id == user_id, Goal12W.is_active.is_(True))
        .order_by(Goal12W.created_at.desc())
    )
    return result.scalars().all()


async def deactivate_all_goals(session: AsyncSession, user_id: int) -> int:
    result = await session.execute(
        update(Goal12W)
        .where(Goal12W.user_id == user_id, Goal12W.is_active.is_(True))
        .values(is_active=False)
    )
    await session.flush()
    return result.rowcount  # type: ignore[return-value]


# =========================================================================
# Weekly Plans
# =========================================================================

async def upsert_weekly_plan(
    session: AsyncSession,
    user_id: int,
    week_number: int,
    year: int,
    lead_actions: list[str],
    constraints: dict | None = None,
) -> WeeklyPlan:
    stmt = select(WeeklyPlan).where(
        WeeklyPlan.user_id == user_id,
        WeeklyPlan.week_number == week_number,
        WeeklyPlan.year == year,
    )
    result = await session.execute(stmt)
    plan = result.scalar_one_or_none()
    if plan is not None:
        plan.lead_actions = lead_actions
        plan.constraints = constraints
        await session.flush()
        return plan
    plan = WeeklyPlan(
        user_id=user_id,
        week_number=week_number,
        year=year,
        lead_actions=lead_actions,
        constraints=constraints,
    )
    session.add(plan)
    await session.flush()
    return plan


async def get_weekly_plan(
    session: AsyncSession, user_id: int, week_number: int, year: int
) -> WeeklyPlan | None:
    result = await session.execute(
        select(WeeklyPlan).where(
            WeeklyPlan.user_id == user_id,
            WeeklyPlan.week_number == week_number,
            WeeklyPlan.year == year,
        )
    )
    return result.scalar_one_or_none()


async def get_current_weekly_plan(session: AsyncSession, user_id: int) -> WeeklyPlan | None:
    """Get the most recent weekly plan."""
    result = await session.execute(
        select(WeeklyPlan)
        .where(WeeklyPlan.user_id == user_id)
        .order_by(WeeklyPlan.year.desc(), WeeklyPlan.week_number.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


# =========================================================================
# Daily Plans
# =========================================================================

async def upsert_daily_plan(
    session: AsyncSession,
    user_id: int,
    plan_date: date,
    tasks: list[dict[str, Any]],
    top_3: list[dict[str, Any]],
    timeblocks: list[dict[str, Any]] | None = None,
    status: str = "active",
) -> DailyPlan:
    stmt = select(DailyPlan).where(
        DailyPlan.user_id == user_id,
        DailyPlan.plan_date == plan_date,
    )
    result = await session.execute(stmt)
    plan = result.scalar_one_or_none()
    if plan is not None:
        plan.tasks = tasks
        plan.top_3 = top_3
        plan.timeblocks = timeblocks
        plan.status = status
        await session.flush()
        return plan
    plan = DailyPlan(
        user_id=user_id,
        plan_date=plan_date,
        tasks=tasks,
        top_3=top_3,
        timeblocks=timeblocks,
        status=status,
    )
    session.add(plan)
    await session.flush()
    return plan


async def get_daily_plan(
    session: AsyncSession, user_id: int, plan_date: date
) -> DailyPlan | None:
    result = await session.execute(
        select(DailyPlan).where(
            DailyPlan.user_id == user_id,
            DailyPlan.plan_date == plan_date,
        )
    )
    return result.scalar_one_or_none()


# =========================================================================
# Checkins
# =========================================================================

async def upsert_checkin(
    session: AsyncSession,
    user_id: int,
    checkin_date: date,
    completed: list[str],
    missed: list[str],
    obstacles: list[str] | None = None,
    lesson: str | None = None,
    next_action: str | None = None,
    confidence_score: int | None = None,
    woop_response: dict | None = None,
) -> Checkin:
    stmt = select(Checkin).where(
        Checkin.user_id == user_id,
        Checkin.checkin_date == checkin_date,
    )
    result = await session.execute(stmt)
    ci = result.scalar_one_or_none()
    if ci is not None:
        ci.completed = completed
        ci.missed = missed
        ci.obstacles = obstacles
        ci.lesson = lesson
        ci.next_action = next_action
        ci.confidence_score = confidence_score
        ci.woop_response = woop_response
        await session.flush()
        return ci
    ci = Checkin(
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
    session.add(ci)
    await session.flush()
    return ci


async def get_checkin(
    session: AsyncSession, user_id: int, checkin_date: date
) -> Checkin | None:
    result = await session.execute(
        select(Checkin).where(
            Checkin.user_id == user_id,
            Checkin.checkin_date == checkin_date,
        )
    )
    return result.scalar_one_or_none()


async def get_checkins_range(
    session: AsyncSession,
    user_id: int,
    start_date: date,
    end_date: date,
) -> Sequence[Checkin]:
    result = await session.execute(
        select(Checkin)
        .where(
            Checkin.user_id == user_id,
            Checkin.checkin_date >= start_date,
            Checkin.checkin_date <= end_date,
        )
        .order_by(Checkin.checkin_date)
    )
    return result.scalars().all()


async def get_checkin_streak(session: AsyncSession, user_id: int) -> int:
    """Count consecutive days with a checkin ending today (or yesterday)."""
    today = date.today()
    result = await session.execute(
        select(Checkin.checkin_date)
        .where(Checkin.user_id == user_id, Checkin.checkin_date <= today)
        .order_by(Checkin.checkin_date.desc())
        .limit(90)
    )
    dates = list(result.scalars().all())
    if not dates:
        return 0
    streak = 0
    expected = today
    # Allow starting from today or yesterday
    if dates[0] == today:
        expected = today
    elif dates[0] == today - timedelta(days=1):
        expected = today - timedelta(days=1)
    else:
        return 0
    for d in dates:
        if d == expected:
            streak += 1
            expected -= timedelta(days=1)
        else:
            break
    return streak


# =========================================================================
# Memory Records
# =========================================================================

async def save_memory_record(
    session: AsyncSession,
    user_id: int,
    record_date: date,
    summary: str,
    record_type: str = "daily",
) -> MemoryRecord:
    rec = MemoryRecord(
        user_id=user_id,
        record_date=record_date,
        summary=summary,
        record_type=record_type,
    )
    session.add(rec)
    await session.flush()
    return rec


async def get_recent_memories(
    session: AsyncSession,
    user_id: int,
    limit: int = 14,
    record_type: str | None = None,
) -> Sequence[MemoryRecord]:
    stmt = (
        select(MemoryRecord)
        .where(MemoryRecord.user_id == user_id)
        .order_by(MemoryRecord.record_date.desc())
        .limit(limit)
    )
    if record_type:
        stmt = stmt.where(MemoryRecord.record_type == record_type)
    result = await session.execute(stmt)
    return result.scalars().all()


# =========================================================================
# Sprints
# =========================================================================

def _next_monday(d: date) -> date:
    """Return d if it's Monday, otherwise the next Monday."""
    days_ahead = (7 - d.weekday()) % 7  # 0 = Monday
    if days_ahead == 0 and d.weekday() == 0:
        return d
    return d + timedelta(days=days_ahead if days_ahead else 7)


def _this_monday(d: date) -> date:
    """Return the Monday of the current week."""
    return d - timedelta(days=d.weekday())


async def create_sprint(
    session: AsyncSession,
    user_id: int,
    start_date: date | None = None,
) -> Sprint:
    """Create a new 12-week sprint. Deactivates any previous active sprint.

    start_date defaults to this Monday if today is Mon, otherwise next Monday.
    end_date = start_date + 83 days (12 weeks - 1 day, i.e. Sunday of week 12).
    """
    today = date.today()
    if start_date is None:
        # If today is Monday, start today; otherwise next Monday
        if today.weekday() == 0:
            start_date = today
        else:
            start_date = _next_monday(today)
    else:
        # Round to Monday
        if start_date.weekday() != 0:
            start_date = _this_monday(start_date)

    end_date = start_date + timedelta(days=83)  # 12 weeks - 1 day

    # Deactivate previous sprints
    await session.execute(
        update(Sprint)
        .where(Sprint.user_id == user_id, Sprint.is_active.is_(True))
        .values(is_active=False)
    )

    sprint = Sprint(
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
        is_active=True,
    )
    session.add(sprint)
    await session.flush()
    logger.info(
        "Created sprint for user %d: %s — %s", user_id, start_date, end_date
    )
    return sprint


async def get_active_sprint(session: AsyncSession, user_id: int) -> Sprint | None:
    """Return the currently active sprint, or None."""
    result = await session.execute(
        select(Sprint)
        .where(Sprint.user_id == user_id, Sprint.is_active.is_(True))
        .order_by(Sprint.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def get_current_week_number(sprint: Sprint, today: date | None = None) -> int:
    """Compute current week number (1–12) from sprint start_date.

    Returns 0 if sprint hasn't started yet, >12 if past the end.
    Clamped to 1..12 for display purposes.
    """
    today = today or date.today()
    if today < sprint.start_date:
        return 0
    days_elapsed = (today - sprint.start_date).days
    week = days_elapsed // 7 + 1
    return min(max(week, 1), 12)


def get_sprint_days_remaining(sprint: Sprint, today: date | None = None) -> int:
    """Return days remaining until sprint end_date (inclusive)."""
    today = today or date.today()
    remaining = (sprint.end_date - today).days
    return max(remaining, 0)


def is_sprint_finished(sprint: Sprint, today: date | None = None) -> bool:
    """Check if the sprint period has ended."""
    today = today or date.today()
    return today > sprint.end_date


# =========================================================================
# Aggregate helpers
# =========================================================================

async def get_weekly_stats(
    session: AsyncSession,
    user_id: int,
    start_date: date,
    end_date: date,
) -> dict[str, int]:
    """Return {planned, completed, missed} counts for a date range."""
    plans = await session.execute(
        select(DailyPlan)
        .where(
            DailyPlan.user_id == user_id,
            DailyPlan.plan_date >= start_date,
            DailyPlan.plan_date <= end_date,
        )
    )
    checkins = await session.execute(
        select(Checkin)
        .where(
            Checkin.user_id == user_id,
            Checkin.checkin_date >= start_date,
            Checkin.checkin_date <= end_date,
        )
    )
    total_planned = 0
    total_completed = 0
    total_missed = 0
    for p in plans.scalars().all():
        total_planned += len(p.tasks or [])
    for c in checkins.scalars().all():
        total_completed += len(c.completed or [])
        total_missed += len(c.missed or [])
    return {
        "planned": total_planned,
        "completed": total_completed,
        "missed": total_missed,
    }

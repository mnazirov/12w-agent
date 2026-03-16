"""SQLAlchemy ORM models for the 12-Week Year assistant."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all models."""
    pass


# ---------------------------------------------------------------------------
# users
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")
    morning_time: Mapped[str] = mapped_column(String(5), default="09:00")
    evening_time: Mapped[str] = mapped_column(String(5), default="21:00")
    preferences: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_chat_response_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_chat_activity: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # relationships
    vision: Mapped[VisionAndWhy | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    goals: Mapped[list[Goal12W]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    weekly_plans: Mapped[list[WeeklyPlan]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    daily_plans: Mapped[list[DailyPlan]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    checkins: Mapped[list[Checkin]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    memory_records: Mapped[list[MemoryRecord]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    sprints: Mapped[list[Sprint]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    google_token: Mapped[GoogleToken | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# google_tokens
# ---------------------------------------------------------------------------
class GoogleToken(Base):
    __tablename__ = "google_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    token_expiry: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    google_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    scopes: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="google_token")


# ---------------------------------------------------------------------------
# vision_and_why
# ---------------------------------------------------------------------------
class VisionAndWhy(Base):
    __tablename__ = "vision_and_why"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    vision: Mapped[str] = mapped_column(Text, nullable=False)
    why_text: Mapped[str] = mapped_column(Text, nullable=False)
    values: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="vision")


# ---------------------------------------------------------------------------
# goals_12w
# ---------------------------------------------------------------------------
class Goal12W(Base):
    __tablename__ = "goals_12w"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    metric: Mapped[str | None] = mapped_column(Text, nullable=True)
    baseline: Mapped[str | None] = mapped_column(Text, nullable=True)
    target: Mapped[str | None] = mapped_column(Text, nullable=True)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    importance: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="goals")


# ---------------------------------------------------------------------------
# weekly_plans
# ---------------------------------------------------------------------------
class WeeklyPlan(Base):
    __tablename__ = "weekly_plans"
    __table_args__ = (
        UniqueConstraint("user_id", "week_number", "year", name="uq_weekly_plan"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    week_number: Mapped[int] = mapped_column(Integer, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    lead_actions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    constraints: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="weekly_plans")


# ---------------------------------------------------------------------------
# daily_plans
# ---------------------------------------------------------------------------
class DailyPlan(Base):
    __tablename__ = "daily_plans"
    __table_args__ = (
        UniqueConstraint("user_id", "plan_date", name="uq_daily_plan"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    tasks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    top_3: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    timeblocks: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="daily_plans")


# ---------------------------------------------------------------------------
# checkins
# ---------------------------------------------------------------------------
class Checkin(Base):
    __tablename__ = "checkins"
    __table_args__ = (
        UniqueConstraint("user_id", "checkin_date", name="uq_checkin"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    checkin_date: Mapped[date] = mapped_column(Date, nullable=False)
    completed: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    missed: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    obstacles: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    lesson: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    woop_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="checkins")


# ---------------------------------------------------------------------------
# memory_records
# ---------------------------------------------------------------------------
class MemoryRecord(Base):
    __tablename__ = "memory_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    record_date: Mapped[date] = mapped_column(Date, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    record_type: Mapped[str] = mapped_column(String(20), nullable=False, default="daily")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="memory_records")


# ---------------------------------------------------------------------------
# sprints (12-week marathons)
# ---------------------------------------------------------------------------
class Sprint(Base):
    __tablename__ = "sprints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="sprints")

"""FSM state groups for multi-step flows."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class SetupStates(StatesGroup):
    """Multi-step setup: vision → why → goals → lead actions → confirm."""
    vision = State()
    why = State()
    goals = State()
    lead_actions = State()
    city = State()
    confirm = State()


class CheckinStates(StatesGroup):
    """Evening check-in: mark tasks → obstacles → lesson → confidence."""
    mark_done = State()
    obstacles = State()
    lesson = State()
    confidence = State()


class PlanStates(StatesGroup):
    """Plan flow: request city when needed before generation."""
    waiting_city = State()

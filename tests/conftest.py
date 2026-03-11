"""Shared test fixtures for the 12-Week Year assistant."""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture()
def mock_openai_response():
    """Factory fixture that returns a mock OpenAI response with given output_text."""

    def _make(output_text: str) -> MagicMock:
        resp = MagicMock()
        resp.output_text = output_text
        return resp

    return _make


@pytest.fixture()
def mock_openai_client(mock_openai_response):
    """Patch the OpenAI client to return a controlled response."""

    def _make(output_text: str):
        client = AsyncMock()
        client.responses.create = AsyncMock(
            return_value=mock_openai_response(output_text)
        )
        return patch(
            "app.services.openai_service.get_client",
            return_value=client,
        )

    return _make


@pytest.fixture()
def sample_plan_json() -> str:
    """Valid JSON that matches DailyPlanResponse schema."""
    return json.dumps({
        "top_3": [
            {
                "task": "Написать 500 слов для статьи",
                "implementation_intention": "Я напишу 500 слов в 09:00 за рабочим столом",
                "starter_step": "Открыть документ и написать первое предложение",
            },
            {
                "task": "30 мин чтения",
                "implementation_intention": "Я буду читать в 13:00 после обеда",
                "starter_step": "Открыть книгу на закладке",
            },
            {
                "task": "Пробежка 5 км",
                "implementation_intention": "Я побегу в 18:00 в парке",
                "starter_step": "Надеть кроссовки и выйти на улицу",
            },
        ],
        "extras": [
            {"task": "Ответить на 3 письма"},
        ],
        "friction_tip": "Положи книгу на стол с утра, чтобы она была на виду",
        "timeblocks": [
            {"task": "Написать 500 слов", "time_slot": "09:00–10:00"},
            {"task": "30 мин чтения", "time_slot": "13:00–13:30"},
            {"task": "Пробежка 5 км", "time_slot": "18:00–19:00"},
        ],
    })


@pytest.fixture()
def sample_checkin_json() -> str:
    """Valid JSON that matches CheckinAnalysis schema."""
    return json.dumps({
        "summary": "Ты сделал 2 из 3 задач — хороший день!",
        "controllable_factors": ["Не выделил конкретное время для чтения"],
        "uncontrollable_factors": ["Внеплановая встреча"],
        "woop": [
            {
                "wish": "Прочитать 30 минут",
                "outcome": "Развитие экспертизы",
                "obstacle": "Откладываю на потом",
                "plan": "Если я замечу, что откладываю, то открою книгу хотя бы на 5 минут",
            },
        ],
        "lesson_prompt": "Что помогло тебе сегодня сфокусироваться?",
        "tomorrow_suggestion": "Поставь чтение первым делом утром, до проверки почты",
    })


@pytest.fixture()
def sample_review_json() -> str:
    """Valid JSON that matches WeeklyReviewResponse schema."""
    return json.dumps({
        "score_pct": 78,
        "wins": ["Стабильно писал каждый день", "Не пропустил ни одной пробежки"],
        "improvements": ["Чтение — 3 из 7 дней", "Вечерний чек-ин пропускал 2 раза"],
        "adjustments": ["Привязать чтение к конкретному триггеру (после обеда)"],
        "vision_reminder": "Ты строишь привычки, которые изменят жизнь через 12 недель",
        "next_week_focus": "Чтение — сделать ежедневным через привязку к обеду",
    })

"""Tests for context gathering in planning_service."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import planning_service as ps


@pytest.mark.asyncio
async def test_gather_day_context_without_city_and_training_skips_weather() -> None:
    orchestrator = SimpleNamespace(call_tool=AsyncMock(return_value={"events": []}))

    context = await ps._gather_day_context(
        user_id=1,
        city=None,
        has_training_goals=False,
        training_type="running",
        mcp_orchestrator=orchestrator,
    )

    assert "Календарь" in context
    assert orchestrator.call_tool.await_count == 1
    first_call = orchestrator.call_tool.await_args_list[0].kwargs
    assert first_call["tool_name"] == "list_events"


@pytest.mark.asyncio
async def test_gather_day_context_with_city_and_training_calls_weather_with_detected_type() -> None:
    orchestrator = SimpleNamespace(
        call_tool=AsyncMock(
            side_effect=[
                {"events": []},
                {
                    "city": "Санкт-Петербург, Россия",
                    "current": {"temperature_c": 12, "description": "Пасмурно"},
                    "forecast": [
                        {
                            "temp_min_c": 8,
                            "temp_max_c": 13,
                            "precipitation_mm": 0,
                            "precipitation_probability_pct": 5,
                            "wind_max_kmh": 10,
                        }
                    ],
                    "training_assessment": {
                        "suitable": True,
                        "recommendation": "Погода подходит",
                        "alternative": None,
                    },
                },
            ]
        )
    )

    await ps._gather_day_context(
        user_id=1,
        city="Санкт-Петербург",
        has_training_goals=True,
        training_type="cycling",
        mcp_orchestrator=orchestrator,
    )

    weather_call = orchestrator.call_tool.await_args_list[1].kwargs
    assert weather_call["tool_name"] == "get_weather_forecast"
    assert weather_call["arguments"]["training_type"] == "cycling"


@pytest.mark.asyncio
async def test_fetch_calendar_context_with_events_formats_schedule() -> None:
    orchestrator = SimpleNamespace(
        call_tool=AsyncMock(
            return_value={
                "events": [
                    {
                        "start": "2026-03-16T10:00:00+03:00",
                        "end": "2026-03-16T11:30:00+03:00",
                        "summary": "Standup",
                    }
                ]
            }
        )
    )

    text = await ps._fetch_calendar_context(orchestrator, user_id=1)

    assert text is not None
    assert "Календарь" in text
    assert "10:00" in text


@pytest.mark.asyncio
async def test_fetch_calendar_context_requires_auth_returns_notice() -> None:
    orchestrator = SimpleNamespace(
        call_tool=AsyncMock(return_value={"requires_auth": True, "error": "auth"})
    )
    notices: list[str] = []

    text = await ps._fetch_calendar_context(orchestrator, user_id=1, notices=notices)

    assert text is None
    assert notices
    assert "/connect_google" in notices[0]


@pytest.mark.asyncio
async def test_fetch_calendar_context_handles_exception() -> None:
    orchestrator = SimpleNamespace(call_tool=AsyncMock(side_effect=RuntimeError("down")))

    text = await ps._fetch_calendar_context(orchestrator, user_id=1)

    assert text is None


@pytest.mark.asyncio
async def test_fetch_weather_context_good_weather_contains_positive_assessment() -> None:
    orchestrator = SimpleNamespace(
        call_tool=AsyncMock(
            return_value={
                "city": "Москва, Россия",
                "current": {"temperature_c": 18, "description": "Ясно"},
                "forecast": [
                    {
                        "temp_min_c": 14,
                        "temp_max_c": 22,
                        "precipitation_mm": 0,
                        "precipitation_probability_pct": 0,
                        "wind_max_kmh": 10,
                    }
                ],
                "training_assessment": {
                    "suitable": True,
                    "recommendation": "Погода подходит для running",
                    "alternative": None,
                },
            }
        )
    )

    text = await ps._fetch_weather_context(orchestrator, city="Москва", training_type="running")

    assert text is not None
    assert "✅" in text
    assert "подходит" in text.lower()


@pytest.mark.asyncio
async def test_fetch_weather_context_bad_weather_contains_alternative() -> None:
    orchestrator = SimpleNamespace(
        call_tool=AsyncMock(
            return_value={
                "city": "Москва, Россия",
                "current": {"temperature_c": 5, "description": "Дождь"},
                "forecast": [
                    {
                        "temp_min_c": 3,
                        "temp_max_c": 6,
                        "precipitation_mm": 12,
                        "precipitation_probability_pct": 95,
                        "wind_max_kmh": 20,
                    }
                ],
                "training_assessment": {
                    "suitable": False,
                    "recommendation": "Не рекомендуется бег на улице",
                    "alternative": "беговая дорожка",
                },
            }
        )
    )

    text = await ps._fetch_weather_context(orchestrator, city="Москва", training_type="running")

    assert text is not None
    assert "⛔" in text
    assert "Альтернатива" in text


@pytest.mark.asyncio
async def test_fetch_weather_context_unavailable_returns_none() -> None:
    orchestrator = SimpleNamespace(
        call_tool=AsyncMock(
            return_value={"error": "server down", "error_type": "server_unavailable"}
        )
    )

    text = await ps._fetch_weather_context(orchestrator, city="Москва", training_type="running")

    assert text is None


def test_detect_training_type_running_keyword() -> None:
    assert ps._detect_training_type("Хочу бег 3 раза в неделю") == "running"


def test_detect_training_type_cycling_keyword() -> None:
    assert ps._detect_training_type("Тренировки на велосипеде") == "cycling"


def test_detect_training_type_defaults_to_running() -> None:
    assert ps._detect_training_type("Фокус на работе и чтении") == "running"


def _sample_plan() -> ps.DailyPlanResponse:
    return ps.DailyPlanResponse.model_validate(
        {
            "top_3": [{"task": "Главная задача"}],
            "extras": [],
            "friction_tip": "",
            "timeblocks": [],
        }
    )


def _patch_repo_defaults(
    monkeypatch: pytest.MonkeyPatch,
    *,
    city: str | None = "Москва",
    goals: list[SimpleNamespace] | None = None,
    lead_actions: list[str] | None = None,
) -> dict[str, AsyncMock]:
    goals = goals if goals is not None else [SimpleNamespace(title="Бег 30 мин", metric=None)]
    weekly = SimpleNamespace(lead_actions=lead_actions if lead_actions is not None else ["Пробежка"])

    mocks = {
        "get_vision": AsyncMock(return_value=SimpleNamespace(vision="Vision", why_text="Why")),
        "get_active_goals": AsyncMock(return_value=goals),
        "get_current_weekly_plan": AsyncMock(return_value=weekly),
        "get_checkin": AsyncMock(return_value=None),
        "get_recent_memories": AsyncMock(return_value=[]),
        "get_active_sprint": AsyncMock(return_value=None),
        "get_user_city": AsyncMock(return_value=city),
        "upsert_daily_plan": AsyncMock(return_value=None),
    }

    for name, mock in mocks.items():
        monkeypatch.setattr(ps.repos, name, mock)

    return mocks


@pytest.mark.asyncio
async def test_generate_daily_plan_includes_day_context_and_calls_openai_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_repo_defaults(monkeypatch)
    gather_mock = AsyncMock(return_value="📅 events\n🌤 weather")
    call_structured_mock = AsyncMock(return_value=_sample_plan())

    monkeypatch.setattr(ps, "_gather_day_context", gather_mock)
    monkeypatch.setattr(ps, "call_structured", call_structured_mock)

    result = await ps.generate_daily_plan(
        session=object(),
        user_id=123,
        mcp_orchestrator=object(),
    )

    assert isinstance(result, ps.DailyPlanResponse)
    assert call_structured_mock.await_count == 1

    kwargs = call_structured_mock.await_args.kwargs
    assert kwargs["variables"]["day_context"] == "📅 events\n🌤 weather"
    assert kwargs["use_tools"] is False


@pytest.mark.asyncio
async def test_generate_daily_plan_without_city_skips_weather_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_repo_defaults(
        monkeypatch,
        city=None,
        goals=[SimpleNamespace(title="Бег утром", metric=None)],
        lead_actions=["Пробежка"],
    )
    monkeypatch.setattr(ps, "call_structured", AsyncMock(return_value=_sample_plan()))

    orchestrator = SimpleNamespace(call_tool=AsyncMock(return_value={"events": []}))

    await ps.generate_daily_plan(
        session=object(),
        user_id=1,
        mcp_orchestrator=orchestrator,
    )

    tool_names = [call.kwargs["tool_name"] for call in orchestrator.call_tool.await_args_list]
    assert "list_events" in tool_names
    assert "get_weather_forecast" not in tool_names


@pytest.mark.asyncio
async def test_generate_daily_plan_city_override_used_for_weather(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_repo_defaults(
        monkeypatch,
        city="Москва",
        goals=[SimpleNamespace(title="Бег по утрам", metric=None)],
        lead_actions=["Пробежка 30 мин"],
    )
    monkeypatch.setattr(ps, "call_structured", AsyncMock(return_value=_sample_plan()))

    orchestrator = SimpleNamespace(
        call_tool=AsyncMock(
            side_effect=[
                {"events": []},
                {
                    "city": "Питер, Россия",
                    "current": {"temperature_c": 10, "description": "Пасмурно"},
                    "forecast": [
                        {
                            "temp_min_c": 7,
                            "temp_max_c": 12,
                            "precipitation_mm": 2,
                            "precipitation_probability_pct": 30,
                            "wind_max_kmh": 12,
                        }
                    ],
                    "training_assessment": {
                        "suitable": True,
                        "recommendation": "Погода подходит",
                        "alternative": None,
                    },
                },
            ]
        )
    )

    await ps.generate_daily_plan(
        session=object(),
        user_id=1,
        mcp_orchestrator=orchestrator,
        city_override="Питер",
    )

    weather_call = orchestrator.call_tool.await_args_list[1].kwargs
    assert weather_call["tool_name"] == "get_weather_forecast"
    assert weather_call["arguments"]["city"] == "Питер"

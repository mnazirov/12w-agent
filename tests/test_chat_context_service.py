"""Tests for free chat context/session management."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.middleware.rate_limit import ChatRateLimiter
from app.services.chat_context_service import ChatContextService


class _SessionContext:
    """Minimal async context manager for session factory mocking."""

    def __init__(self, session) -> None:
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return None


def _session_factory(session):
    return lambda: _SessionContext(session)


@pytest.mark.asyncio
async def test_get_previous_response_id_returns_id_for_fresh_session(monkeypatch) -> None:
    session = AsyncMock()
    monkeypatch.setattr(
        "app.services.chat_context_service.repos.get_last_chat_activity",
        AsyncMock(return_value=datetime.now(timezone.utc) - timedelta(minutes=15)),
    )
    get_id = AsyncMock(return_value="resp_123")
    monkeypatch.setattr(
        "app.services.chat_context_service.repos.get_chat_response_id",
        get_id,
    )
    clear_mock = AsyncMock()
    monkeypatch.setattr(
        "app.services.chat_context_service.repos.clear_chat_session",
        clear_mock,
    )

    service = ChatContextService(
        session_factory=_session_factory(session),
        session_timeout_minutes=120,
    )
    result = await service.get_previous_response_id(42)

    assert result == "resp_123"
    clear_mock.assert_not_called()
    get_id.assert_awaited_once_with(session, 42)


@pytest.mark.asyncio
async def test_get_previous_response_id_clears_expired_session(monkeypatch) -> None:
    session = AsyncMock()
    monkeypatch.setattr(
        "app.services.chat_context_service.repos.get_last_chat_activity",
        AsyncMock(return_value=datetime.now(timezone.utc) - timedelta(minutes=121)),
    )
    clear_mock = AsyncMock()
    monkeypatch.setattr(
        "app.services.chat_context_service.repos.clear_chat_session",
        clear_mock,
    )
    monkeypatch.setattr(
        "app.services.chat_context_service.repos.get_chat_response_id",
        AsyncMock(return_value="resp_old"),
    )

    service = ChatContextService(
        session_factory=_session_factory(session),
        session_timeout_minutes=120,
    )
    result = await service.get_previous_response_id(42)

    assert result is None
    clear_mock.assert_awaited_once_with(session, 42)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_previous_response_id_returns_none_without_activity(monkeypatch) -> None:
    session = AsyncMock()
    monkeypatch.setattr(
        "app.services.chat_context_service.repos.get_last_chat_activity",
        AsyncMock(return_value=None),
    )
    get_id = AsyncMock(return_value="resp_ignored")
    monkeypatch.setattr(
        "app.services.chat_context_service.repos.get_chat_response_id",
        get_id,
    )

    service = ChatContextService(
        session_factory=_session_factory(session),
        session_timeout_minutes=120,
    )
    result = await service.get_previous_response_id(42)

    assert result is None
    get_id.assert_not_called()


@pytest.mark.asyncio
async def test_save_response_id_calls_repo_update(monkeypatch) -> None:
    session = AsyncMock()
    update_mock = AsyncMock()
    monkeypatch.setattr(
        "app.services.chat_context_service.repos.update_chat_response_id",
        update_mock,
    )

    service = ChatContextService(session_factory=_session_factory(session))
    await service.save_response_id(7, "resp_new")

    update_mock.assert_awaited_once_with(session, 7, "resp_new")
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_clear_session_calls_repo_clear(monkeypatch) -> None:
    session = AsyncMock()
    clear_mock = AsyncMock()
    monkeypatch.setattr(
        "app.services.chat_context_service.repos.clear_chat_session",
        clear_mock,
    )

    service = ChatContextService(session_factory=_session_factory(session))
    await service.clear_session(7)

    clear_mock.assert_awaited_once_with(session, 7)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_build_user_context_uses_memory_and_goals(monkeypatch) -> None:
    session = AsyncMock()
    monkeypatch.setattr(
        "app.services.chat_context_service.memory_service.get_context",
        AsyncMock(return_value="[2026-03-14] Завершил 2 из 3 задач."),
    )
    monkeypatch.setattr(
        "app.services.chat_context_service.repos.get_active_goals",
        AsyncMock(
            return_value=[
                SimpleNamespace(title="Привести в порядок бэклог"),
                SimpleNamespace(title="Делать 30 мин спорта ежедневно"),
            ]
        ),
    )
    monkeypatch.setattr(
        "app.services.chat_context_service.repos.get_active_sprint",
        AsyncMock(return_value=SimpleNamespace()),
    )
    monkeypatch.setattr(
        "app.services.chat_context_service.repos.get_current_week_number",
        lambda _: 5,
    )
    monkeypatch.setattr(
        "app.services.chat_context_service.repos.get_sprint_days_remaining",
        lambda _: 49,
    )

    service = ChatContextService(session_factory=_session_factory(session))
    result = await service.build_user_context(7)

    assert "Недавняя история" in result
    assert "Активные цели" in result
    assert "Привести в порядок бэклог" in result
    assert "Текущая неделя: 5 из 12" in result
    assert "Осталось дней: 49" in result


@pytest.mark.asyncio
async def test_build_user_context_returns_empty_on_memory_error(monkeypatch) -> None:
    session = AsyncMock()
    monkeypatch.setattr(
        "app.services.chat_context_service.memory_service.get_context",
        AsyncMock(side_effect=RuntimeError("boom")),
    )
    monkeypatch.setattr(
        "app.services.chat_context_service.repos.get_active_goals",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "app.services.chat_context_service.repos.get_active_sprint",
        AsyncMock(return_value=None),
    )

    service = ChatContextService(session_factory=_session_factory(session))
    result = await service.build_user_context(7)

    assert result == ""


def test_chat_rate_limiter_first_15_allowed() -> None:
    limiter = ChatRateLimiter(max_per_minute=15)
    for _ in range(15):
        assert limiter.check(1) is True


def test_chat_rate_limiter_16th_blocked() -> None:
    limiter = ChatRateLimiter(max_per_minute=15)
    for _ in range(15):
        assert limiter.check(1) is True
    assert limiter.check(1) is False


def test_chat_rate_limiter_allows_again_after_minute() -> None:
    limiter = ChatRateLimiter(max_per_minute=15)
    for _ in range(15):
        assert limiter.check(1) is True
    assert limiter.check(1) is False

    limiter._timestamps[1] = [datetime.now(timezone.utc) - timedelta(minutes=2)]
    assert limiter.check(1) is True

"""Tests for OAuth callback HTTP endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from app.web.oauth_callback import routes


async def _build_client(bot=None, auth_service=None) -> TestClient:
    app = web.Application()
    app.add_routes(routes)
    app["bot"] = bot if bot is not None else AsyncMock()
    app["google_auth_service"] = auth_service
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    return client


def _auth_mock() -> MagicMock:
    auth = MagicMock()
    auth.validate_state = MagicMock(return_value=123)
    auth.exchange_code = AsyncMock(return_value={"access_token": "acc", "refresh_token": "ref"})
    auth.get_user_email = AsyncMock(return_value="u@example.com")
    auth.save_tokens = AsyncMock()
    return auth


@pytest.mark.asyncio
async def test_callback_success_flow() -> None:
    bot = AsyncMock()
    auth = _auth_mock()
    auth.exchange_code.return_value = {
        "access_token": "acc",
        "refresh_token": "ref",
        "expires_in": 3600,
    }
    auth.get_user_email.return_value = "u@example.com"

    client = await _build_client(bot=bot, auth_service=auth)
    try:
        resp = await client.get("/oauth/google/callback?code=X&state=valid")
        text = await resp.text()
    finally:
        await client.close()

    assert resp.status == 200
    assert "Google-аккаунт подключён" in text
    auth.exchange_code.assert_awaited_once_with("X")
    auth.save_tokens.assert_awaited_once()
    bot.send_message.assert_awaited()


@pytest.mark.asyncio
async def test_callback_denied_by_user() -> None:
    bot = AsyncMock()
    auth = _auth_mock()
    auth.validate_state.return_value = 555

    client = await _build_client(bot=bot, auth_service=auth)
    try:
        resp = await client.get("/oauth/google/callback?error=access_denied&state=ok")
        text = await resp.text()
    finally:
        await client.close()

    assert resp.status == 200
    assert "Подключение отменено" in text
    bot.send_message.assert_awaited()


@pytest.mark.asyncio
async def test_callback_missing_state_returns_400() -> None:
    auth = _auth_mock()
    client = await _build_client(auth_service=auth)
    try:
        resp = await client.get("/oauth/google/callback?code=X")
    finally:
        await client.close()

    assert resp.status == 400


@pytest.mark.asyncio
async def test_callback_expired_state_returns_400() -> None:
    auth = _auth_mock()
    auth.validate_state.return_value = None

    client = await _build_client(auth_service=auth)
    try:
        resp = await client.get("/oauth/google/callback?code=X&state=expired")
    finally:
        await client.close()

    assert resp.status == 400


@pytest.mark.asyncio
async def test_callback_garbage_state_returns_400() -> None:
    auth = _auth_mock()
    auth.validate_state.return_value = None

    client = await _build_client(auth_service=auth)
    try:
        resp = await client.get("/oauth/google/callback?code=X&state=garbage")
    finally:
        await client.close()

    assert resp.status == 400


@pytest.mark.asyncio
async def test_callback_exchange_code_failure_returns_500() -> None:
    bot = AsyncMock()
    auth = _auth_mock()
    auth.validate_state.return_value = 42
    auth.exchange_code.side_effect = ValueError("fail")

    client = await _build_client(bot=bot, auth_service=auth)
    try:
        resp = await client.get("/oauth/google/callback?code=X&state=ok")
    finally:
        await client.close()

    assert resp.status == 500
    bot.send_message.assert_awaited()


@pytest.mark.asyncio
async def test_health_endpoint() -> None:
    auth = _auth_mock()
    client = await _build_client(auth_service=auth)
    try:
        resp = await client.get("/oauth/google/health")
        data = await resp.json()
    finally:
        await client.close()

    assert resp.status == 200
    assert data == {"status": "ok"}

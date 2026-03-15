"""Tests for GoogleAuthService OAuth and token lifecycle logic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from app.services.crypto_service import TokenEncryptor
from app.services.google_auth_service import GoogleAuthService


@dataclass
class _FakeResponse:
    status: int
    payload: dict

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return self.payload


class _FakeHTTPSession:
    def __init__(self, post_items=None, get_items=None) -> None:
        self._post_items = list(post_items or [])
        self._get_items = list(get_items or [])
        self.post_calls: list[dict] = []
        self.get_calls: list[dict] = []
        self.closed = False

    def post(self, url, data=None, params=None, headers=None):
        self.post_calls.append(
            {"url": url, "data": data, "params": params, "headers": headers}
        )
        item = self._post_items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def get(self, url, headers=None):
        self.get_calls.append({"url": url, "headers": headers})
        item = self._get_items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self):
        self.closed = True


def _build_service(repo=None) -> GoogleAuthService:
    return GoogleAuthService(
        client_id="cid",
        client_secret="secret",
        redirect_uri="https://example.com/oauth/google/callback",
        encryptor=TokenEncryptor(TokenEncryptor.generate_key()),
        repo=repo or AsyncMock(),
    )


def test_generate_auth_url_contains_required_params() -> None:
    service = _build_service()

    url = service.generate_auth_url(telegram_id=123456)
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert "state" in query
    assert query["client_id"] == ["cid"]
    assert query["redirect_uri"] == ["https://example.com/oauth/google/callback"]
    assert query["response_type"] == ["code"]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert "https://www.googleapis.com/auth/calendar.events" in query["scope"][0]


def test_generate_auth_url_state_round_trip() -> None:
    service = _build_service()
    url = service.generate_auth_url(telegram_id=42)
    state = parse_qs(urlparse(url).query)["state"][0]
    assert service.validate_state(state) == 42


def test_validate_state_expired_returns_none(monkeypatch) -> None:
    service = _build_service()
    now = 1_700_000_000
    monkeypatch.setattr("app.services.google_auth_service.time.time", lambda: now)
    url = service.generate_auth_url(telegram_id=7)
    state = parse_qs(urlparse(url).query)["state"][0]
    monkeypatch.setattr(
        "app.services.google_auth_service.time.time",
        lambda: now + service.STATE_MAX_AGE_SECONDS + 1,
    )
    assert service.validate_state(state) is None


def test_validate_state_garbage_returns_none() -> None:
    service = _build_service()
    assert service.validate_state("garbage") is None


def test_validate_state_invalid_json_returns_none() -> None:
    service = _build_service()
    state = service._encryptor.encrypt("not-json")
    assert service.validate_state(state) is None


@pytest.mark.asyncio
async def test_exchange_code_success() -> None:
    service = _build_service()
    service._http = _FakeHTTPSession(
        post_items=[
            _FakeResponse(
                status=200,
                payload={
                    "access_token": "acc",
                    "refresh_token": "ref",
                    "expires_in": 3600,
                    "scope": "x y",
                },
            )
        ]
    )

    out = await service.exchange_code("code-1")
    assert out["access_token"] == "acc"
    assert out["refresh_token"] == "ref"


@pytest.mark.asyncio
async def test_exchange_code_error_raises_value_error() -> None:
    service = _build_service()
    service._http = _FakeHTTPSession(
        post_items=[_FakeResponse(status=400, payload={"error": "bad_request"})]
    )

    with pytest.raises(ValueError):
        await service.exchange_code("bad")


@pytest.mark.asyncio
async def test_get_valid_access_token_not_expired() -> None:
    repo = AsyncMock()
    service = _build_service(repo=repo)
    encrypted = service._encryptor.encrypt("valid-token")
    repo.get_google_tokens.return_value = SimpleNamespace(
        access_token_encrypted=encrypted,
        refresh_token_encrypted=service._encryptor.encrypt("refresh"),
        token_expiry=datetime.now(timezone.utc) + timedelta(minutes=5),
    )

    token = await service.get_valid_access_token(user_id=1)
    assert token == "valid-token"


@pytest.mark.asyncio
async def test_get_valid_access_token_expired_refreshes() -> None:
    repo = AsyncMock()
    service = _build_service(repo=repo)
    service._http = _FakeHTTPSession(
        post_items=[_FakeResponse(status=200, payload={"access_token": "new", "expires_in": 1000})]
    )
    repo.get_google_tokens.return_value = SimpleNamespace(
        access_token_encrypted=service._encryptor.encrypt("old"),
        refresh_token_encrypted=service._encryptor.encrypt("refresh"),
        token_expiry=datetime.now(timezone.utc) - timedelta(minutes=1),
    )

    token = await service.get_valid_access_token(user_id=1)
    assert token == "new"
    repo.update_google_access_token.assert_awaited()


@pytest.mark.asyncio
async def test_get_valid_access_token_no_record_returns_none() -> None:
    repo = AsyncMock()
    repo.get_google_tokens.return_value = None
    service = _build_service(repo=repo)

    assert await service.get_valid_access_token(user_id=1) is None


@pytest.mark.asyncio
async def test_get_valid_access_token_refresh_failed_returns_none() -> None:
    repo = AsyncMock()
    service = _build_service(repo=repo)
    service._http = _FakeHTTPSession(
        post_items=[_FakeResponse(status=400, payload={"error": "invalid_grant"})]
    )
    repo.get_google_tokens.return_value = SimpleNamespace(
        access_token_encrypted=service._encryptor.encrypt("old"),
        refresh_token_encrypted=service._encryptor.encrypt("refresh"),
        token_expiry=datetime.now(timezone.utc) - timedelta(minutes=1),
    )

    assert await service.get_valid_access_token(user_id=1) is None


@pytest.mark.asyncio
async def test_revoke_and_delete_success() -> None:
    repo = AsyncMock()
    service = _build_service(repo=repo)
    service._http = _FakeHTTPSession(post_items=[_FakeResponse(status=200, payload={})])
    repo.get_google_tokens.return_value = SimpleNamespace(
        access_token_encrypted=service._encryptor.encrypt("tok"),
    )

    ok = await service.revoke_and_delete(user_id=1)
    assert ok is True
    repo.delete_google_tokens.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_revoke_and_delete_even_if_revoke_fails() -> None:
    repo = AsyncMock()
    service = _build_service(repo=repo)
    service._http = _FakeHTTPSession(post_items=[RuntimeError("network down")])
    repo.get_google_tokens.return_value = SimpleNamespace(
        access_token_encrypted=service._encryptor.encrypt("tok"),
    )

    ok = await service.revoke_and_delete(user_id=2)
    assert ok is True
    repo.delete_google_tokens.assert_awaited_once_with(2)


@pytest.mark.asyncio
async def test_is_connected_passthrough() -> None:
    repo = AsyncMock()
    repo.has_google_connected.return_value = True
    service = _build_service(repo=repo)
    assert await service.is_connected(1) is True


@pytest.mark.asyncio
async def test_save_tokens_encrypts_and_saves() -> None:
    repo = AsyncMock()
    repo.get_user_by_telegram_id.return_value = SimpleNamespace(id=99)
    service = _build_service(repo=repo)
    token_data = {
        "access_token": "acc",
        "refresh_token": "ref",
        "expires_in": 3600,
        "scope": "a b",
    }

    await service.save_tokens(telegram_id=123, token_data=token_data, email="user@example.com")

    kwargs = repo.save_google_tokens.await_args.kwargs
    assert kwargs["user_id"] == 99
    assert kwargs["telegram_id"] == 123
    assert kwargs["google_email"] == "user@example.com"
    assert kwargs["scopes"] == "a b"
    assert kwargs["access_token_enc"] != "acc"
    assert kwargs["refresh_token_enc"] != "ref"
    assert service._encryptor.decrypt(kwargs["access_token_enc"]) == "acc"
    assert service._encryptor.decrypt(kwargs["refresh_token_enc"]) == "ref"


@pytest.mark.asyncio
async def test_save_tokens_user_not_found_raises() -> None:
    repo = AsyncMock()
    repo.get_user_by_telegram_id.return_value = None
    service = _build_service(repo=repo)

    with pytest.raises(ValueError):
        await service.save_tokens(
            telegram_id=123,
            token_data={
                "access_token": "acc",
                "refresh_token": "ref",
            },
            email=None,
        )

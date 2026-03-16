"""Google OAuth2 Authorization Code flow and token lifecycle management."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import aiohttp
from cryptography.fernet import InvalidToken

from app.services.crypto_service import TokenEncryptor

logger = logging.getLogger(__name__)


class GoogleAuthService:
    """Google OAuth2 orchestration with encrypted token storage."""

    GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
    GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
    GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

    SCOPES = [
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
        "openid",
        "email",
    ]
    STATE_MAX_AGE_SECONDS = 600

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        encryptor: TokenEncryptor,
        repo: Any,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._encryptor = encryptor
        self._repo = repo
        self._http: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        self._http = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
        )

    async def stop(self) -> None:
        if self._http and not self._http.closed:
            await self._http.close()

    def generate_auth_url(self, telegram_id: int) -> str:
        """Generate a user-facing Google consent URL with encrypted state."""
        state_payload = json.dumps(
            {
                "tid": telegram_id,
                "ts": int(time.time()),
            }
        )
        state = self._encryptor.encrypt(state_payload)
        params = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{self.GOOGLE_AUTH_URL}?{urlencode(params)}"

    def validate_state(self, state: str) -> int | None:
        """Validate encrypted OAuth state and return telegram_id."""
        try:
            payload = json.loads(self._encryptor.decrypt(state))
        except (InvalidToken, json.JSONDecodeError):
            logger.warning("Invalid OAuth state")
            return None
        except Exception:
            logger.exception("Unexpected OAuth state validation error")
            return None

        ts = payload.get("ts")
        if not isinstance(ts, int):
            return None
        age = int(time.time()) - ts
        if age > self.STATE_MAX_AGE_SECONDS:
            logger.warning("OAuth state expired: age=%d", age)
            return None

        tid = payload.get("tid")
        if not isinstance(tid, int):
            return None
        return tid

    async def exchange_code(self, code: str) -> dict[str, Any]:
        """Exchange authorization code for token payload."""
        if self._http is None:
            raise RuntimeError("GoogleAuthService is not started")

        data = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self._redirect_uri,
        }
        async with self._http.post(self.GOOGLE_TOKEN_URL, data=data) as resp:
            body = await resp.json()
            if resp.status != 200 or "access_token" not in body:
                logger.error("Google token exchange failed: %s", body)
                raise ValueError("Token exchange failed")
            if "refresh_token" not in body:
                raise ValueError("No refresh token returned by Google")
            return body

    async def get_user_email(self, access_token: str) -> str | None:
        """Fetch Google account email for user-facing status."""
        if self._http is None:
            raise RuntimeError("GoogleAuthService is not started")
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            async with self._http.get(self.GOOGLE_USERINFO_URL, headers=headers) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data.get("email")
        except Exception:
            logger.exception("Google userinfo request failed")
            return None

    async def save_tokens(
        self,
        telegram_id: int,
        token_data: dict[str, Any],
        email: str | None,
    ) -> None:
        """Encrypt and persist OAuth credentials mapped to internal user id."""
        user = await self._repo.get_user_by_telegram_id(telegram_id)
        if user is None:
            raise ValueError(f"User not found for telegram_id={telegram_id}")

        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        if not access_token or not refresh_token:
            raise ValueError("Missing OAuth access/refresh token")

        expires_in = int(token_data.get("expires_in", 3600))
        token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        await self._repo.save_google_tokens(
            user_id=user.id,
            telegram_id=telegram_id,
            access_token_enc=self._encryptor.encrypt(access_token),
            refresh_token_enc=self._encryptor.encrypt(refresh_token),
            token_expiry=token_expiry,
            google_email=email,
            scopes=str(token_data.get("scope", "")),
        )

    async def get_valid_access_token(self, user_id: int) -> str | None:
        """Return valid access token, refreshing transparently when needed."""
        record = await self._repo.get_google_tokens(user_id)
        if record is None:
            return None

        expiry = record.token_expiry
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)

        if expiry > datetime.now(timezone.utc) + timedelta(seconds=60):
            try:
                return self._encryptor.decrypt(record.access_token_encrypted)
            except InvalidToken:
                logger.error("Access token decryption failed for user_id=%d", user_id)
                return None

        return await self._refresh_access_token(user_id, record)

    async def _refresh_access_token(self, user_id: int, record: Any) -> str | None:
        if self._http is None:
            raise RuntimeError("GoogleAuthService is not started")

        try:
            refresh_token = self._encryptor.decrypt(record.refresh_token_encrypted)
        except InvalidToken:
            logger.error("Refresh token decryption failed for user_id=%d", user_id)
            return None

        data = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        try:
            async with self._http.post(self.GOOGLE_TOKEN_URL, data=data) as resp:
                body = await resp.json()
                if resp.status != 200 or "access_token" not in body:
                    logger.error("Google refresh failed for user_id=%d: %s", user_id, body)
                    return None

                access_token = body["access_token"]
                expires_in = int(body.get("expires_in", 3600))
                token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
                await self._repo.update_google_access_token(
                    user_id=user_id,
                    access_token_enc=self._encryptor.encrypt(access_token),
                    token_expiry=token_expiry,
                )
                return access_token
        except Exception:
            logger.exception("Google refresh request failed for user_id=%d", user_id)
            return None

    async def revoke_and_delete(self, user_id: int) -> bool:
        """Try to revoke token remotely and always delete it locally."""
        if self._http is None:
            raise RuntimeError("GoogleAuthService is not started")

        record = await self._repo.get_google_tokens(user_id)
        if record is None:
            return False

        try:
            token = self._encryptor.decrypt(record.access_token_encrypted)
            async with self._http.post(
                self.GOOGLE_REVOKE_URL,
                params={"token": token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as resp:
                if resp.status not in (200, 400):
                    logger.warning(
                        "Google revoke returned status=%d for user_id=%d",
                        resp.status,
                        user_id,
                    )
        except Exception:
            logger.exception("Google revoke request failed for user_id=%d", user_id)

        await self._repo.delete_google_tokens(user_id)
        return True

    async def is_connected(self, user_id: int) -> bool:
        return await self._repo.has_google_connected(user_id)

    async def get_connected_email(self, user_id: int) -> str | None:
        row = await self._repo.get_google_tokens(user_id)
        return row.google_email if row else None

    async def get_token_expiry(self, user_id: int) -> datetime | None:
        row = await self._repo.get_google_tokens(user_id)
        return row.token_expiry if row else None

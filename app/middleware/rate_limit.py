"""Simple in-memory rate limiter for free chat fallback."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone


class ChatRateLimiter:
    """Allow at most N messages per rolling minute per user."""

    def __init__(self, max_per_minute: int = 15) -> None:
        self._max = max_per_minute
        self._timestamps: dict[int, list[datetime]] = defaultdict(list)

    def check(self, user_id: int) -> bool:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=1)

        timestamps = [ts for ts in self._timestamps[user_id] if ts > cutoff]
        if len(timestamps) >= self._max:
            self._timestamps[user_id] = timestamps
            return False

        timestamps.append(now)
        self._timestamps[user_id] = timestamps
        return True

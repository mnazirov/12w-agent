"""Standalone MCP server for activity tracking and motivation context generation."""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

from mcp.server.fastmcp import FastMCP

MCP_HOST = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.getenv("MCP_PORT", "8001"))

mcp = FastMCP(
    "12w-motivation-tracker",
    instructions="Track activity, evaluate engagement, and prepare motivation context.",
    host=MCP_HOST,
    port=MCP_PORT,
)

DB_PATH = os.getenv("MCP_DB_PATH", "/data/motivation.db")


@contextmanager
def get_db():
    """Open SQLite connection with WAL and foreign keys enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Initialize required SQLite schema for motivation tracker."""
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                details TEXT DEFAULT '',
                created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
            );
            CREATE INDEX IF NOT EXISTS idx_activity_user ON activity_log(user_id, created_at);

            CREATE TABLE IF NOT EXISTS motivation_config (
                user_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 1,
                interval_hours REAL DEFAULT 8.0,
                style TEXT DEFAULT 'balanced',
                quiet_start INTEGER DEFAULT 23,
                quiet_end INTEGER DEFAULT 7,
                last_sent_at TEXT,
                created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
                updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
            );

            CREATE TABLE IF NOT EXISTS motivation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                message_type TEXT NOT NULL,
                engagement_level TEXT,
                message TEXT NOT NULL,
                created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
            );
            CREATE INDEX IF NOT EXISTS idx_motiv_hist_user ON motivation_history(user_id, created_at);

            CREATE TABLE IF NOT EXISTS achievement_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                period TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
            );
            """
        )


init_db()


def _ensure_config(conn, user_id: int) -> dict:
    """Ensure motivation config exists for user and return it."""
    row = conn.execute(
        "SELECT * FROM motivation_config WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO motivation_config (user_id) VALUES (?)",
            (user_id,),
        )
        row = conn.execute(
            "SELECT * FROM motivation_config WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return dict(row) if row is not None else {}


def _calc_streak(conn, user_id: int) -> tuple[int, int]:
    """Calculate current and longest daily activity streak for a user."""
    rows = conn.execute(
        """
        SELECT DISTINCT date(created_at) AS d
        FROM activity_log
        WHERE user_id = ?
        ORDER BY d DESC
        """,
        (user_id,),
    ).fetchall()

    if not rows:
        return 0, 0

    days_desc = [datetime.fromisoformat(row["d"]).date() for row in rows if row["d"]]
    if not days_desc:
        return 0, 0

    days_set = set(days_desc)
    today = datetime.utcnow().date()

    current_streak = 0
    cursor = today
    while cursor in days_set:
        current_streak += 1
        cursor -= timedelta(days=1)

    days_sorted = sorted(days_set)
    longest_streak = 1
    run = 1
    for idx in range(1, len(days_sorted)):
        if (days_sorted[idx] - days_sorted[idx - 1]).days == 1:
            run += 1
        else:
            run = 1
        if run > longest_streak:
            longest_streak = run

    return current_streak, longest_streak


@mcp.tool()
def log_activity(user_id: int, action: str, details: str = "") -> str:
    """Log a single user activity action.

    Args:
        user_id: Telegram user id.
        action: Activity type label.
        details: Optional details string (trimmed to 200 chars).
    """
    with get_db() as conn:
        _ensure_config(conn, user_id)
        conn.execute(
            "INSERT INTO activity_log (user_id, action, details) VALUES (?, ?, ?)",
            (user_id, action, (details or "")[:200]),
        )
    return json.dumps({"status": "ok"})


@mcp.tool()
def log_activities_batch(activities_json: str) -> str:
    """Log many user activity actions in one transaction.

    Args:
        activities_json: JSON array of objects with user_id/action/details.
    """
    try:
        activities = json.loads(activities_json)
        if not isinstance(activities, list):
            raise ValueError("activities_json must be a JSON array")

        count = 0
        with get_db() as conn:
            rows: list[tuple[int, str, str]] = []
            for item in activities:
                if not isinstance(item, dict):
                    continue
                user_id = int(item.get("user_id"))
                action = str(item.get("action", "")).strip()
                if not action:
                    continue
                details = str(item.get("details", ""))[:200]
                _ensure_config(conn, user_id)
                rows.append((user_id, action, details))

            if rows:
                conn.executemany(
                    "INSERT INTO activity_log (user_id, action, details) VALUES (?, ?, ?)",
                    rows,
                )
            count = len(rows)

        return json.dumps({"status": "ok", "count": count})
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})


@mcp.tool()
def get_achievement_report(user_id: int, days: int = 7) -> str:
    """Build an achievement report for the recent period.

    Args:
        user_id: Telegram user id.
        days: Report window in days.
    """
    now = datetime.utcnow()
    window = max(1, int(days))
    since = (now - timedelta(days=window)).isoformat(timespec="seconds")
    prev_since = (now - timedelta(days=window * 2)).isoformat(timespec="seconds")

    with get_db() as conn:
        breakdown_rows = conn.execute(
            """
            SELECT action, COUNT(*) AS c
            FROM activity_log
            WHERE user_id = ? AND created_at >= ?
            GROUP BY action
            """,
            (user_id, since),
        ).fetchall()
        breakdown = {row["action"]: int(row["c"]) for row in breakdown_rows}
        total = sum(breakdown.values())

        prev_total = int(
            conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM activity_log
                WHERE user_id = ? AND created_at >= ? AND created_at < ?
                """,
                (user_id, prev_since, since),
            ).fetchone()["c"]
        )

        daily_rows = conn.execute(
            """
            SELECT date(created_at) AS d, COUNT(*) AS c
            FROM activity_log
            WHERE user_id = ? AND created_at >= ?
            GROUP BY d
            ORDER BY d
            """,
            (user_id, since),
        ).fetchall()
        daily = [{"date": row["d"], "count": int(row["c"])} for row in daily_rows]

        current_streak, longest_streak = _calc_streak(conn, user_id)

        last_row = conn.execute(
            """
            SELECT created_at
            FROM activity_log
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()

    last_activity = last_row["created_at"] if last_row else None
    hours_since = None
    if last_activity:
        last_dt = datetime.fromisoformat(last_activity)
        hours_since = round((now - last_dt).total_seconds() / 3600, 1)

    if prev_total == 0:
        trend = "new"
    elif total >= prev_total * 1.2:
        trend = "improving"
    elif total <= prev_total * 0.8:
        trend = "declining"
    else:
        trend = "stable"

    consistency = round(len(daily) / max(window, 1), 2)

    return json.dumps(
        {
            "user_id": user_id,
            "period_days": window,
            "total_activities": total,
            "breakdown": breakdown,
            "daily": daily,
            "current_streak": current_streak,
            "longest_streak": longest_streak,
            "consistency": consistency,
            "trend": trend,
            "hours_since_last": hours_since,
            "last_activity_at": last_activity,
            "generated_at": now.isoformat(timespec="seconds"),
        }
    )


@mcp.tool()
def check_engagement(user_id: int) -> str:
    """Evaluate current user engagement and motivation trigger status.

    Args:
        user_id: Telegram user id.
    """
    now = datetime.utcnow()
    week_since = (now - timedelta(days=7)).isoformat(timespec="seconds")

    with get_db() as conn:
        cfg = _ensure_config(conn, user_id)

        last_row = conn.execute(
            """
            SELECT created_at
            FROM activity_log
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()

        week_cnt = int(
            conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM activity_log
                WHERE user_id = ? AND created_at >= ?
                """,
                (user_id, week_since),
            ).fetchone()["c"]
        )

        total_cnt = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM activity_log WHERE user_id = ?",
                (user_id,),
            ).fetchone()["c"]
        )

    hours_inactive = None
    if last_row is None:
        engagement_level = "new_user"
    else:
        last_dt = datetime.fromisoformat(last_row["created_at"])
        hours_inactive = round((now - last_dt).total_seconds() / 3600, 1)
        if hours_inactive < 4:
            engagement_level = "highly_active"
        elif hours_inactive < 12:
            engagement_level = "active"
        elif hours_inactive < 24:
            engagement_level = "moderate"
        elif hours_inactive < 48:
            engagement_level = "declining"
        else:
            engagement_level = "inactive"

    enabled = bool(cfg.get("enabled", 1))
    should_send = enabled and total_cnt >= 3

    if should_send:
        last_sent_at = cfg.get("last_sent_at")
        if last_sent_at:
            elapsed_hours = (now - datetime.fromisoformat(last_sent_at)).total_seconds() / 3600
            if elapsed_hours < float(cfg.get("interval_hours", 8.0)):
                should_send = False

        qs = max(0, min(23, int(cfg.get("quiet_start", 23))))
        qe = max(0, min(23, int(cfg.get("quiet_end", 7))))
        cur_hour = now.hour
        if qs > qe:
            is_quiet = cur_hour >= qs or cur_hour < qe
        else:
            is_quiet = qs <= cur_hour < qe
        if is_quiet:
            should_send = False

    return json.dumps(
        {
            "user_id": user_id,
            "engagement_level": engagement_level,
            "hours_inactive": hours_inactive,
            "should_send_motivation": bool(should_send),
            "week_activity_count": week_cnt,
            "total_activities": total_cnt,
            "style": cfg.get("style", "balanced"),
            "checked_at": now.isoformat(timespec="seconds"),
        }
    )


@mcp.tool()
def generate_motivation_context(user_id: int) -> str:
    """Generate consolidated context used to craft a motivation message.

    Args:
        user_id: Telegram user id.
    """
    engagement = json.loads(check_engagement(user_id))
    achievements = json.loads(get_achievement_report(user_id, days=7))

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT message_type, engagement_level, message, created_at
            FROM motivation_history
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 3
            """,
            (user_id,),
        ).fetchall()

    recent_motivations = [dict(row) for row in rows]

    mapping = {
        "highly_active": ("praise", "celebratory"),
        "active": ("support", "encouraging"),
        "moderate": ("nudge", "gentle_reminder"),
        "declining": ("challenge", "motivating"),
        "inactive": ("reactivation", "warm_welcome_back"),
        "new_user": ("welcome", "friendly"),
    }
    level = engagement.get("engagement_level", "new_user")
    recommended_type, recommended_tone = mapping.get(level, ("support", "encouraging"))

    return json.dumps(
        {
            "user_id": user_id,
            "engagement": engagement,
            "achievements": achievements,
            "recent_motivations": recent_motivations,
            "recommended_type": recommended_type,
            "recommended_tone": recommended_tone,
            "style": engagement.get("style", "balanced"),
        }
    )


@mcp.tool()
def get_motivation_config(user_id: int) -> str:
    """Fetch motivation configuration for a user.

    Args:
        user_id: Telegram user id.
    """
    with get_db() as conn:
        cfg = _ensure_config(conn, user_id)
    return json.dumps(cfg)


@mcp.tool()
def update_motivation_config(
    user_id: int,
    enabled: bool | None = None,
    interval_hours: float | None = None,
    style: str | None = None,
    quiet_start: int | None = None,
    quiet_end: int | None = None,
) -> str:
    """Update motivation configuration fields for a user.

    Args:
        user_id: Telegram user id.
        enabled: Enable or disable automatic motivation.
        interval_hours: Interval between messages in hours (fractional values are allowed).
        style: One of gentle, balanced, intense.
        quiet_start: Quiet-hours start (0-23, UTC).
        quiet_end: Quiet-hours end (0-23, UTC).
    """
    with get_db() as conn:
        _ensure_config(conn, user_id)

        fields: list[str] = []
        values: list[object] = []

        if enabled is not None:
            fields.append("enabled = ?")
            values.append(1 if enabled else 0)

        if interval_hours is not None:
            iv = max((1.0 / 60.0), min(48.0, float(interval_hours)))
            fields.append("interval_hours = ?")
            values.append(iv)

        if style is not None and style in {"gentle", "balanced", "intense"}:
            fields.append("style = ?")
            values.append(style)

        if quiet_start is not None:
            qs = max(0, min(23, int(quiet_start)))
            fields.append("quiet_start = ?")
            values.append(qs)

        if quiet_end is not None:
            qe = max(0, min(23, int(quiet_end)))
            fields.append("quiet_end = ?")
            values.append(qe)

        fields.append("updated_at = strftime('%Y-%m-%dT%H:%M:%S','now')")

        sql = f"UPDATE motivation_config SET {', '.join(fields)} WHERE user_id = ?"
        values.append(user_id)
        conn.execute(sql, values)

        cfg = conn.execute(
            "SELECT * FROM motivation_config WHERE user_id = ?",
            (user_id,),
        ).fetchone()

    return json.dumps(dict(cfg) if cfg is not None else {})


@mcp.tool()
def record_motivation_sent(
    user_id: int,
    message_type: str,
    engagement_level: str | None,
    message: str,
) -> str:
    """Record a sent motivation message and update last_sent_at.

    Args:
        user_id: Telegram user id.
        message_type: Motivation message category.
        engagement_level: Engagement level at send time.
        message: Sent motivation text.
    """
    with get_db() as conn:
        _ensure_config(conn, user_id)
        conn.execute(
            """
            INSERT INTO motivation_history (user_id, message_type, engagement_level, message)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, message_type, engagement_level, message),
        )
        conn.execute(
            """
            UPDATE motivation_config
            SET last_sent_at = strftime('%Y-%m-%dT%H:%M:%S','now'),
                updated_at = strftime('%Y-%m-%dT%H:%M:%S','now')
            WHERE user_id = ?
            """,
            (user_id,),
        )
    return json.dumps({"status": "ok"})


@mcp.tool()
def get_users_needing_motivation() -> str:
    """Return enabled users who should receive motivation now.

    Args:
        None.
    """
    with get_db() as conn:
        rows = conn.execute(
            "SELECT user_id FROM motivation_config WHERE enabled = 1"
        ).fetchall()
    users = []
    for row in rows:
        uid = int(row["user_id"])
        state = json.loads(check_engagement(uid))
        if state.get("should_send_motivation"):
            users.append(uid)

    return json.dumps(
        {
            "users": users,
            "checked_at": datetime.utcnow().isoformat(timespec="seconds"),
        }
    )

"""Read-only aggregate queries behind the admin surface.

Everything here takes a `Database` and returns plain dicts, so the same
functions serve the bot's admin commands and the web dashboard without either
knowing about the other.
"""

from __future__ import annotations

import time
from typing import Any

from bot.storage.db import Database, rows_to_dicts

DAY = 86_400.0


def day_bounds(days: int, now: float | None = None) -> tuple[float, float]:
    """The half-open interval covering the last `days` days, ending now."""
    now = now if now is not None else time.time()
    return now - days * DAY, now


async def summary(db: Database, days: int = 1, now: float | None = None) -> dict[str, Any]:
    """Headline numbers over the last `days` days."""
    since, until = day_bounds(days, now)
    row = await db.fetch_one(
        """
        SELECT
            COUNT(DISTINCT user_id)                     AS users,
            COUNT(*)                                    AS attempts,
            COALESCE(SUM(is_correct), 0)                AS correct,
            COUNT(DISTINCT user_id || '|' || expression) AS problems
        FROM attempts
        WHERE ts >= ? AND ts < ?
        """,
        (since, until),
    )
    data = dict(row) if row else {"users": 0, "attempts": 0, "correct": 0, "problems": 0}
    attempts = int(data["attempts"] or 0)
    data["success_rate"] = (int(data["correct"] or 0) / attempts) if attempts else 0.0
    data["days"] = days
    return data


async def daily_activity(db: Database, days: int = 30, now: float | None = None) -> list[dict[str, Any]]:
    """One row per day: distinct users, attempts, correct answers."""
    since, until = day_bounds(days, now)
    rows = await db.fetch_all(
        """
        SELECT
            DATE(ts, 'unixepoch', 'localtime') AS day,
            COUNT(DISTINCT user_id)            AS users,
            COUNT(*)                           AS attempts,
            COALESCE(SUM(is_correct), 0)       AS correct
        FROM attempts
        WHERE ts >= ? AND ts < ?
        GROUP BY day
        ORDER BY day
        """,
        (since, until),
    )
    return rows_to_dicts(rows)


async def user_list(db: Database) -> list[dict[str, Any]]:
    """Every known user with their totals, most recently active first."""
    rows = await db.fetch_all(
        """
        SELECT
            u.user_id,
            u.tg_username,
            u.full_name,
            u.grade_profile,
            u.difficulty,
            u.score,
            u.banned,
            u.first_seen,
            u.last_seen,
            COALESCE(a.attempts, 0)  AS attempts,
            COALESCE(a.correct, 0)   AS correct,
            COALESCE(s.sessions, 0)  AS sessions
        FROM users u
        LEFT JOIN (
            SELECT user_id, COUNT(*) AS attempts, SUM(is_correct) AS correct
            FROM attempts GROUP BY user_id
        ) a ON a.user_id = u.user_id
        LEFT JOIN (
            SELECT user_id, COUNT(*) AS sessions FROM sessions GROUP BY user_id
        ) s ON s.user_id = u.user_id
        ORDER BY u.last_seen DESC
        """
    )
    result = rows_to_dicts(rows)
    for item in result:
        attempts = int(item["attempts"] or 0)
        item["success_rate"] = (int(item["correct"] or 0) / attempts) if attempts else 0.0
    return result


async def user_detail(db: Database, user_id: int) -> dict[str, Any] | None:
    row = await db.get_user(user_id)
    if row is None:
        return None
    detail = dict(row)
    totals = await db.fetch_one(
        """
        SELECT COUNT(*) AS attempts, COALESCE(SUM(is_correct), 0) AS correct,
               MIN(ts) AS first_attempt, MAX(ts) AS last_attempt
        FROM attempts WHERE user_id = ?
        """,
        (user_id,),
    )
    detail.update(dict(totals) if totals else {})
    attempts = int(detail.get("attempts") or 0)
    detail["success_rate"] = (int(detail.get("correct") or 0) / attempts) if attempts else 0.0
    detail["sessions"] = int(
        await db.fetch_value("SELECT COUNT(*) FROM sessions WHERE user_id = ?", (user_id,), 0)
    )
    return detail


async def user_progress(db: Database, user_id: int, limit: int = 500) -> list[dict[str, Any]]:
    """Score, difficulty and profile over time — the series the charts plot.

    This is what answers "has the child quietly slid back to easy problems?".
    """
    rows = await db.fetch_all(
        """
        SELECT ts, score_after AS score, difficulty, grade_profile, is_correct
        FROM attempts
        WHERE user_id = ?
        ORDER BY ts DESC
        LIMIT ?
        """,
        (user_id, limit),
    )
    return list(reversed(rows_to_dicts(rows)))


async def recent_attempts(db: Database, user_id: int, limit: int = 50) -> list[dict[str, Any]]:
    rows = await db.fetch_all(
        """
        SELECT ts, expression, correct_answer, given_answer, attempt_no,
               is_correct, difficulty, grade_profile, score_after, ms_to_answer
        FROM attempts
        WHERE user_id = ?
        ORDER BY ts DESC
        LIMIT ?
        """,
        (user_id, limit),
    )
    return rows_to_dicts(rows)


async def user_sessions(db: Database, user_id: int, limit: int = 50) -> list[dict[str, Any]]:
    rows = await db.fetch_all(
        """
        SELECT id, started_at, ended_at, end_reason, tasks_total, tasks_correct
        FROM sessions WHERE user_id = ?
        ORDER BY started_at DESC LIMIT ?
        """,
        (user_id, limit),
    )
    return rows_to_dicts(rows)


async def recent_events(
    db: Database, user_id: int | None = None, kinds: tuple[str, ...] = (), limit: int = 100
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if user_id is not None:
        clauses.append("user_id = ?")
        params.append(user_id)
    if kinds:
        clauses.append(f"kind IN ({','.join('?' * len(kinds))})")
        params.extend(kinds)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    rows = await db.fetch_all(
        f"SELECT id, user_id, ts, kind, payload_json FROM events {where} ORDER BY ts DESC LIMIT ?",
        params,
    )
    return rows_to_dicts(rows)


async def banned_users(db: Database) -> list[dict[str, Any]]:
    rows = await db.fetch_all(
        "SELECT user_id, full_name, tg_username, ban_reason, banned_by, banned_at "
        "FROM users WHERE banned = 1 ORDER BY banned_at DESC"
    )
    return rows_to_dicts(rows)

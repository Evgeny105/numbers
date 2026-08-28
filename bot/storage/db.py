"""SQLite database: connection, schema and small write helpers.

Redis holds the current problem and attempt counter and nothing else. Everything
worth looking at later — who came, what they answered, how their difficulty
moved — lives here, on a named volume, so it survives container replacement and
a Redis flush alike.

The schema is applied at startup as an ordered list of idempotent statements
guarded by a version row. At this size that is enough; a migration framework
would be another dependency for no benefit.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Iterable, Sequence

import aiosqlite

_LOGGER = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id       INTEGER PRIMARY KEY,
        tg_username   TEXT,
        full_name     TEXT,
        first_seen    REAL NOT NULL,
        last_seen     REAL NOT NULL,
        grade_profile TEXT,
        difficulty    INTEGER NOT NULL DEFAULT 1,
        score         INTEGER NOT NULL DEFAULT 0,
        banned        INTEGER NOT NULL DEFAULT 0,
        ban_reason    TEXT,
        banned_by     INTEGER,
        banned_at     REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id       INTEGER NOT NULL,
        started_at    REAL NOT NULL,
        ended_at      REAL,
        end_reason    TEXT,
        tasks_total   INTEGER NOT NULL DEFAULT 0,
        tasks_correct INTEGER NOT NULL DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, started_at)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_open ON sessions(user_id) WHERE ended_at IS NULL",
    """
    CREATE TABLE IF NOT EXISTS attempts (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id     INTEGER,
        user_id        INTEGER NOT NULL,
        ts             REAL NOT NULL,
        expression     TEXT NOT NULL,
        correct_answer INTEGER NOT NULL,
        given_answer   TEXT,
        attempt_no     INTEGER NOT NULL,
        is_correct     INTEGER NOT NULL,
        difficulty     INTEGER NOT NULL,
        grade_profile  TEXT NOT NULL,
        score_after    INTEGER NOT NULL,
        ms_to_answer   INTEGER
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_attempts_user_ts ON attempts(user_id, ts)",
    "CREATE INDEX IF NOT EXISTS idx_attempts_ts ON attempts(ts)",
    """
    CREATE TABLE IF NOT EXISTS events (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      INTEGER,
        ts           REAL NOT NULL,
        kind         TEXT NOT NULL,
        payload_json TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_events_user_ts ON events(user_id, ts)",
    "CREATE INDEX IF NOT EXISTS idx_events_kind_ts ON events(kind, ts)",
    """
    CREATE TABLE IF NOT EXISTS phrases (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        category    TEXT NOT NULL,
        text        TEXT NOT NULL,
        provider    TEXT NOT NULL,
        model       TEXT,
        created_at  REAL NOT NULL,
        disabled    INTEGER NOT NULL DEFAULT 0,
        disabled_at REAL,
        disabled_by INTEGER,
        UNIQUE(category, text)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_phrases_category ON phrases(category, disabled)",
    """
    CREATE TABLE IF NOT EXISTS phrase_uses (
        phrase_id INTEGER NOT NULL,
        user_id   INTEGER NOT NULL,
        ts        REAL NOT NULL,
        PRIMARY KEY (phrase_id, user_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_phrase_uses_user ON phrase_uses(user_id, ts)",
)


class Database:
    """A thin async wrapper over one SQLite file.

    One connection is enough: the bot is a single process serving a handful of
    users, and SQLite serialises writes anyway. WAL mode lets the dashboard
    process read concurrently without ever blocking the bot.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._conn: aiosqlite.Connection | None = None

    @property
    def connection(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected; call connect() first")
        return self._conn

    async def connect(self) -> "Database":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self.migrate()
        _LOGGER.info("database ready at %s (schema v%s)", self.path, SCHEMA_VERSION)
        return self

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def __aenter__(self) -> "Database":
        return await self.connect()

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def migrate(self) -> None:
        for statement in _SCHEMA:
            await self.connection.execute(statement)
        await self.connection.execute(
            "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(SCHEMA_VERSION),),
        )
        await self.connection.commit()

    # -- low level helpers -------------------------------------------------

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> aiosqlite.Cursor:
        cursor = await self.connection.execute(sql, params)
        await self.connection.commit()
        return cursor

    async def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> list[aiosqlite.Row]:
        async with self.connection.execute(sql, params) as cursor:
            return list(await cursor.fetchall())

    async def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> aiosqlite.Row | None:
        async with self.connection.execute(sql, params) as cursor:
            return await cursor.fetchone()

    async def fetch_value(self, sql: str, params: Sequence[Any] = (), default: Any = None) -> Any:
        row = await self.fetch_one(sql, params)
        if row is None:
            return default
        value = row[0]
        return default if value is None else value

    # -- users -------------------------------------------------------------

    async def upsert_user(
        self, user_id: int, tg_username: str | None, full_name: str | None, now: float | None = None
    ) -> aiosqlite.Row:
        now = now if now is not None else time.time()
        await self.execute(
            """
            INSERT INTO users(user_id, tg_username, full_name, first_seen, last_seen)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                tg_username = COALESCE(excluded.tg_username, users.tg_username),
                full_name   = COALESCE(excluded.full_name, users.full_name),
                last_seen   = excluded.last_seen
            """,
            (user_id, tg_username, full_name, now, now),
        )
        row = await self.fetch_one("SELECT * FROM users WHERE user_id = ?", (user_id,))
        assert row is not None
        return row

    async def get_user(self, user_id: int) -> aiosqlite.Row | None:
        return await self.fetch_one("SELECT * FROM users WHERE user_id = ?", (user_id,))

    async def set_user_fields(self, user_id: int, **fields: Any) -> None:
        if not fields:
            return
        allowed = {
            "tg_username",
            "full_name",
            "grade_profile",
            "difficulty",
            "score",
            "banned",
            "ban_reason",
            "banned_by",
            "banned_at",
            "last_seen",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Unknown user fields: {sorted(unknown)}")
        assignments = ", ".join(f"{name} = ?" for name in fields)
        await self.execute(
            f"UPDATE users SET {assignments} WHERE user_id = ?",
            (*fields.values(), user_id),
        )

    async def is_banned(self, user_id: int) -> bool:
        return bool(
            await self.fetch_value(
                "SELECT banned FROM users WHERE user_id = ?", (user_id,), default=0
            )
        )

    async def set_ban(
        self, user_id: int, banned: bool, by_admin: int | None = None, reason: str | None = None
    ) -> None:
        now = time.time()
        await self.execute(
            """
            INSERT INTO users(user_id, first_seen, last_seen, banned, ban_reason, banned_by, banned_at)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                banned = excluded.banned,
                ban_reason = excluded.ban_reason,
                banned_by = excluded.banned_by,
                banned_at = excluded.banned_at
            """,
            (user_id, now, now, int(banned), reason, by_admin, now if banned else None),
        )
        await self.record_event(
            user_id,
            "ban" if banned else "unban",
            {"by": by_admin, "reason": reason},
        )

    # -- sessions ----------------------------------------------------------

    async def open_session(self, user_id: int, now: float | None = None) -> int:
        now = now if now is not None else time.time()
        cursor = await self.execute(
            "INSERT INTO sessions(user_id, started_at) VALUES(?, ?)", (user_id, now)
        )
        session_id = cursor.lastrowid
        assert session_id is not None
        await self.record_event(user_id, "session_start", {"session_id": session_id}, now)
        return session_id

    async def current_session_id(self, user_id: int) -> int | None:
        row = await self.fetch_one(
            "SELECT id FROM sessions WHERE user_id = ? AND ended_at IS NULL "
            "ORDER BY started_at DESC LIMIT 1",
            (user_id,),
        )
        return int(row["id"]) if row else None

    async def ensure_session(self, user_id: int, idle_timeout: float, now: float | None = None) -> int:
        """Return the user's open session, starting a new one after a long gap."""
        now = now if now is not None else time.time()
        row = await self.fetch_one(
            "SELECT id, started_at FROM sessions WHERE user_id = ? AND ended_at IS NULL "
            "ORDER BY started_at DESC LIMIT 1",
            (user_id,),
        )
        if row is not None:
            last = await self.fetch_value(
                "SELECT MAX(ts) FROM attempts WHERE session_id = ?",
                (row["id"],),
                default=row["started_at"],
            )
            if now - float(last) <= idle_timeout:
                return int(row["id"])
            await self.close_session(int(row["id"]), reason="idle", now=float(last))
        return await self.open_session(user_id, now)

    async def close_session(
        self, session_id: int, reason: str = "stop", now: float | None = None
    ) -> None:
        now = now if now is not None else time.time()
        await self.execute(
            """
            UPDATE sessions SET
                ended_at = ?,
                end_reason = ?,
                tasks_total = (
                    SELECT COUNT(DISTINCT expression) FROM attempts WHERE session_id = sessions.id
                ),
                tasks_correct = (
                    SELECT COUNT(*) FROM attempts
                    WHERE session_id = sessions.id AND is_correct = 1
                )
            WHERE id = ? AND ended_at IS NULL
            """,
            (now, reason, session_id),
        )

    async def close_user_sessions(self, user_id: int, reason: str = "stop") -> None:
        rows = await self.fetch_all(
            "SELECT id FROM sessions WHERE user_id = ? AND ended_at IS NULL", (user_id,)
        )
        for row in rows:
            await self.close_session(int(row["id"]), reason=reason)

    # -- attempts and events ----------------------------------------------

    async def record_attempt(
        self,
        *,
        user_id: int,
        session_id: int | None,
        expression: str,
        correct_answer: int,
        given_answer: str | None,
        attempt_no: int,
        is_correct: bool,
        difficulty: int,
        grade_profile: str,
        score_after: int,
        ms_to_answer: int | None,
        now: float | None = None,
    ) -> int:
        now = now if now is not None else time.time()
        cursor = await self.execute(
            """
            INSERT INTO attempts(
                session_id, user_id, ts, expression, correct_answer, given_answer,
                attempt_no, is_correct, difficulty, grade_profile, score_after, ms_to_answer
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                user_id,
                now,
                expression,
                correct_answer,
                given_answer,
                attempt_no,
                int(is_correct),
                difficulty,
                grade_profile,
                score_after,
                ms_to_answer,
            ),
        )
        attempt_id = cursor.lastrowid
        assert attempt_id is not None
        return attempt_id

    async def record_event(
        self,
        user_id: int | None,
        kind: str,
        payload: dict[str, Any] | None = None,
        now: float | None = None,
    ) -> None:
        now = now if now is not None else time.time()
        await self.execute(
            "INSERT INTO events(user_id, ts, kind, payload_json) VALUES(?, ?, ?, ?)",
            (user_id, now, kind, json.dumps(payload, ensure_ascii=False) if payload else None),
        )


def rows_to_dicts(rows: Iterable[aiosqlite.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]

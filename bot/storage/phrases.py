"""The phrase pool: storage, per-user selection, and eviction.

Usage is recorded per user rather than globally. A phrase the child has already
seen is still fresh for anyone else, so two users never deplete each other's
supply — and the same phrase can quite reasonably repeat for the same user once
they have worked through the whole pool, which is the intended behaviour.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from bot.storage.db import Database, rows_to_dicts


@dataclass(frozen=True)
class StoredPhrase:
    id: int
    category: str
    text: str
    provider: str
    model: str | None


async def pick_for_user(db: Database, category: str, user_id: int) -> StoredPhrase | None:
    """Pick a phrase for this user: unseen first, otherwise least recently seen.

    `phrase_uses.ts IS NULL` sorts first because unseen phrases are exactly the
    rows the left join fails to match.
    """
    row = await db.fetch_one(
        """
        SELECT p.id, p.category, p.text, p.provider, p.model
        FROM phrases p
        LEFT JOIN phrase_uses u ON u.phrase_id = p.id AND u.user_id = ?
        WHERE p.category = ? AND p.disabled = 0
        ORDER BY (u.ts IS NOT NULL), u.ts ASC, RANDOM()
        LIMIT 1
        """,
        (user_id, category),
    )
    if row is None:
        return None
    return StoredPhrase(
        id=int(row["id"]),
        category=str(row["category"]),
        text=str(row["text"]),
        provider=str(row["provider"]),
        model=row["model"],
    )


async def mark_used(db: Database, phrase_id: int, user_id: int, now: float | None = None) -> None:
    """Record that this user has now seen this phrase."""
    now = now if now is not None else time.time()
    await db.execute(
        """
        INSERT INTO phrase_uses(phrase_id, user_id, ts) VALUES(?, ?, ?)
        ON CONFLICT(phrase_id, user_id) DO UPDATE SET ts = excluded.ts
        """,
        (phrase_id, user_id, now),
    )


async def unseen_count(db: Database, category: str, user_id: int) -> int:
    """How many usable phrases in this category this user has never received."""
    return int(
        await db.fetch_value(
            """
            SELECT COUNT(*)
            FROM phrases p
            LEFT JOIN phrase_uses u ON u.phrase_id = p.id AND u.user_id = ?
            WHERE p.category = ? AND p.disabled = 0 AND u.ts IS NULL
            """,
            (user_id, category),
            default=0,
        )
    )


async def usable_count(db: Database, category: str) -> int:
    return int(
        await db.fetch_value(
            "SELECT COUNT(*) FROM phrases WHERE category = ? AND disabled = 0",
            (category,),
            default=0,
        )
    )


async def add_phrase(
    db: Database, category: str, text: str, provider: str, model: str | None
) -> int | None:
    """Store a new phrase. Returns None if this exact text is already present."""
    cursor = await db.execute(
        """
        INSERT INTO phrases(category, text, provider, model, created_at)
        VALUES(?, ?, ?, ?, ?)
        ON CONFLICT(category, text) DO NOTHING
        """,
        (category, text, provider, model, time.time()),
    )
    return cursor.lastrowid if cursor.rowcount else None


async def existing_texts(db: Database, category: str, include_disabled: bool = True) -> list[str]:
    """Phrases already in this category, for use as negative examples."""
    sql = "SELECT text FROM phrases WHERE category = ?"
    if not include_disabled:
        sql += " AND disabled = 0"
    rows = await db.fetch_all(sql + " ORDER BY created_at DESC", (category,))
    return [str(row["text"]) for row in rows]


async def disabled_texts(db: Database, category: str) -> list[str]:
    rows = await db.fetch_all(
        "SELECT text FROM phrases WHERE category = ? AND disabled = 1 ORDER BY disabled_at DESC",
        (category,),
    )
    return [str(row["text"]) for row in rows]


async def set_disabled(
    db: Database, phrase_id: int, disabled: bool, by_admin: int | None = None
) -> None:
    await db.execute(
        "UPDATE phrases SET disabled = ?, disabled_at = ?, disabled_by = ? WHERE id = ?",
        (int(disabled), time.time() if disabled else None, by_admin, phrase_id),
    )


async def evict_over_cap(db: Database, category: str, cap: int) -> int:
    """Trim a category back to `cap` phrases, dropping the least useful first.

    Least useful means: fewest users have ever seen it, then oldest. A phrase
    nobody has seen yet and that was generated long ago is the one adding least
    to variety, so it goes before a popular recent one.
    """
    surplus = await usable_count(db, category) - cap
    if surplus <= 0:
        return 0
    rows = await db.fetch_all(
        """
        SELECT p.id
        FROM phrases p
        LEFT JOIN phrase_uses u ON u.phrase_id = p.id
        WHERE p.category = ? AND p.disabled = 0
        GROUP BY p.id
        ORDER BY COUNT(u.user_id) ASC, p.created_at ASC
        LIMIT ?
        """,
        (category, surplus),
    )
    for row in rows:
        await db.execute("DELETE FROM phrase_uses WHERE phrase_id = ?", (row["id"],))
        await db.execute("DELETE FROM phrases WHERE id = ?", (row["id"],))
    return len(rows)


async def pool_overview(db: Database) -> list[dict[str, Any]]:
    """Per-category counts for the admin surface."""
    rows = await db.fetch_all(
        """
        SELECT category,
               SUM(CASE WHEN disabled = 0 THEN 1 ELSE 0 END) AS usable,
               SUM(CASE WHEN disabled = 1 THEN 1 ELSE 0 END) AS disabled
        FROM phrases GROUP BY category ORDER BY category
        """
    )
    return rows_to_dicts(rows)


async def phrases_in_category(db: Database, category: str) -> list[dict[str, Any]]:
    rows = await db.fetch_all(
        """
        SELECT p.id, p.text, p.provider, p.model, p.created_at, p.disabled,
               COUNT(u.user_id) AS seen_by
        FROM phrases p
        LEFT JOIN phrase_uses u ON u.phrase_id = p.id
        WHERE p.category = ?
        GROUP BY p.id
        ORDER BY p.disabled ASC, p.created_at DESC
        """,
        (category,),
    )
    return rows_to_dicts(rows)

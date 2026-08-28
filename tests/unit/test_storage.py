"""Storage behaviour: history is durable, sessions close, phrases are per-user."""

from __future__ import annotations

import time

import pytest

from bot.storage import phrases as phrase_store
from bot.storage import queries
from bot.storage.db import Database


async def _seed_attempt(db: Database, user_id: int, correct: bool, ts: float | None = None) -> None:
    session_id = await db.ensure_session(user_id, 1800)
    await db.record_attempt(
        user_id=user_id,
        session_id=session_id,
        expression="2 + 2",
        correct_answer=4,
        given_answer="4" if correct else "5",
        attempt_no=1,
        is_correct=correct,
        difficulty=2,
        grade_profile="grade3",
        score_after=1 if correct else 0,
        ms_to_answer=1500,
        now=ts,
    )


class TestUsers:
    async def test_upsert_creates_then_updates(self, db: Database) -> None:
        first = await db.upsert_user(1, "kid", "Ребёнок")
        assert first["first_seen"] == first["last_seen"]

        later = await db.upsert_user(1, None, "Ребёнок Новый")
        assert later["first_seen"] == first["first_seen"]
        assert later["full_name"] == "Ребёнок Новый"
        # A missing username must not erase the one already known.
        assert later["tg_username"] == "kid"

    async def test_unknown_field_is_refused(self, db: Database) -> None:
        await db.upsert_user(1, "kid", "Ребёнок")
        with pytest.raises(ValueError):
            await db.set_user_fields(1, nonsense=1)

    async def test_ban_round_trip_records_events(self, db: Database) -> None:
        await db.set_ban(7, True, by_admin=99, reason="флуд")
        assert await db.is_banned(7) is True
        await db.set_ban(7, False, by_admin=99)
        assert await db.is_banned(7) is False

        kinds = [event["kind"] for event in await queries.recent_events(db, 7)]
        assert "ban" in kinds and "unban" in kinds


class TestSessions:
    async def test_same_session_within_the_idle_window(self, db: Database) -> None:
        await db.upsert_user(1, "kid", "Ребёнок")
        first = await db.ensure_session(1, idle_timeout=1800)
        second = await db.ensure_session(1, idle_timeout=1800)
        assert first == second

    async def test_a_long_gap_starts_a_new_session(self, db: Database) -> None:
        await db.upsert_user(1, "kid", "Ребёнок")
        first = await db.ensure_session(1, idle_timeout=1800)
        await _seed_attempt(db, 1, True, ts=time.time() - 7200)
        second = await db.ensure_session(1, idle_timeout=1800)
        assert second != first

        closed = await db.fetch_one("SELECT * FROM sessions WHERE id = ?", (first,))
        assert closed is not None and closed["ended_at"] is not None
        assert closed["end_reason"] == "idle"

    async def test_closing_writes_totals_and_keeps_history(self, db: Database) -> None:
        await db.upsert_user(1, "kid", "Ребёнок")
        await _seed_attempt(db, 1, True)
        await _seed_attempt(db, 1, False)
        await db.close_user_sessions(1)

        session = await db.fetch_one("SELECT * FROM sessions WHERE user_id = 1")
        assert session is not None
        assert session["tasks_correct"] == 1
        assert session["ended_at"] is not None
        # `/stop` must never delete recorded answers.
        assert len(await queries.recent_attempts(db, 1)) == 2


class TestQueries:
    async def test_summary_and_daily_activity(self, db: Database) -> None:
        await db.upsert_user(1, "kid", "Ребёнок")
        await _seed_attempt(db, 1, True)
        await _seed_attempt(db, 1, False)

        summary = await queries.summary(db, days=1)
        assert summary["users"] == 1
        assert summary["attempts"] == 2
        assert summary["correct"] == 1
        assert summary["success_rate"] == pytest.approx(0.5)

        activity = await queries.daily_activity(db, days=2)
        assert activity and activity[-1]["attempts"] == 2

    async def test_user_progress_is_ordered_forward_in_time(self, db: Database) -> None:
        await db.upsert_user(1, "kid", "Ребёнок")
        for index in range(5):
            await _seed_attempt(db, 1, True, ts=time.time() - (5 - index))
        series = await queries.user_progress(db, 1)
        assert [row["ts"] for row in series] == sorted(row["ts"] for row in series)

    async def test_user_list_reports_totals(self, db: Database) -> None:
        await db.upsert_user(1, "kid", "Ребёнок")
        await _seed_attempt(db, 1, True)
        listing = await queries.user_list(db)
        assert listing[0]["attempts"] == 1
        assert listing[0]["success_rate"] == 1.0


class TestPhrasePool:
    async def test_unseen_phrases_come_first(self, db: Database) -> None:
        for text in ("первая", "вторая", "третья"):
            await phrase_store.add_phrase(db, "correct_1st", text, "stub", "m")

        seen: set[str] = set()
        for _ in range(3):
            phrase = await phrase_store.pick_for_user(db, "correct_1st", user_id=1)
            assert phrase is not None
            assert phrase.text not in seen
            seen.add(phrase.text)
            await phrase_store.mark_used(db, phrase.id, user_id=1)
        assert len(seen) == 3

    async def test_usage_is_per_user(self, db: Database) -> None:
        await phrase_store.add_phrase(db, "correct_1st", "единственная", "stub", "m")
        first = await phrase_store.pick_for_user(db, "correct_1st", user_id=1)
        assert first is not None
        await phrase_store.mark_used(db, first.id, user_id=1)

        # The same phrase is still brand new to a different user.
        assert await phrase_store.unseen_count(db, "correct_1st", user_id=1) == 0
        assert await phrase_store.unseen_count(db, "correct_1st", user_id=2) == 1
        second = await phrase_store.pick_for_user(db, "correct_1st", user_id=2)
        assert second is not None and second.id == first.id

    async def test_exhausted_pool_returns_the_least_recently_seen(self, db: Database) -> None:
        ids = []
        for text in ("а", "б"):
            ids.append(await phrase_store.add_phrase(db, "correct_1st", text, "stub", "m"))
        await phrase_store.mark_used(db, ids[0], 1, now=100.0)
        await phrase_store.mark_used(db, ids[1], 1, now=200.0)

        picked = await phrase_store.pick_for_user(db, "correct_1st", user_id=1)
        assert picked is not None and picked.id == ids[0]

    async def test_disabled_phrases_are_never_served(self, db: Database) -> None:
        phrase_id = await phrase_store.add_phrase(db, "correct_1st", "плохая", "stub", "m")
        assert phrase_id is not None
        await phrase_store.set_disabled(db, phrase_id, True, by_admin=1)

        assert await phrase_store.pick_for_user(db, "correct_1st", user_id=1) is None
        assert await phrase_store.disabled_texts(db, "correct_1st") == ["плохая"]

    async def test_duplicates_are_not_stored_twice(self, db: Database) -> None:
        assert await phrase_store.add_phrase(db, "correct_1st", "одна", "stub", "m") is not None
        assert await phrase_store.add_phrase(db, "correct_1st", "одна", "stub", "m") is None
        assert await phrase_store.usable_count(db, "correct_1st") == 1

    async def test_eviction_trims_to_the_cap(self, db: Database) -> None:
        for index in range(8):
            await phrase_store.add_phrase(db, "correct_1st", f"фраза {index}", "stub", "m")
        removed = await phrase_store.evict_over_cap(db, "correct_1st", cap=5)
        assert removed == 3
        assert await phrase_store.usable_count(db, "correct_1st") == 5


class TestDurability:
    async def test_history_survives_reopening_the_file(self, db: Database, tmp_path) -> None:
        await db.upsert_user(1, "kid", "Ребёнок")
        await _seed_attempt(db, 1, True)
        path = db.path
        await db.close()

        reopened = await Database(path).connect()
        try:
            assert len(await queries.recent_attempts(reopened, 1)) == 1
        finally:
            await reopened.close()

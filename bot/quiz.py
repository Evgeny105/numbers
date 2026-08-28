"""The quiz loop: issuing problems, judging answers, moving the score.

Every state write here is awaited. The previous version fired them off as
unawaited `asyncio.create_task` calls, which meant a score could land after the
next problem had already been generated — and, because the tasks were never
referenced, the event loop was free to collect them mid-flight. Awaiting costs
a few milliseconds and buys an ordering guarantee.
"""

from __future__ import annotations

import html
import logging
import time
from dataclasses import dataclass

from aiogram.fsm.context import FSMContext

from bot import texts
from bot.math import generate
from bot.math.profiles import get_profile
from bot.storage.db import Database

_LOGGER = logging.getLogger(__name__)

MAX_ATTEMPTS = 3

#: Score bounds. The scale is deliberately short: it is a progress dial for a
#: child, not a leaderboard.
MIN_SCORE = 0
MAX_SCORE = 49

#: How many points of progress buy one step of difficulty.
POINTS_PER_LEVEL = 10


@dataclass(frozen=True)
class UserProgress:
    """The user's standing, as stored on their database row."""

    profile: str
    difficulty: int
    score: int


def difficulty_for_score(score: int, profile_key: str) -> int:
    """Map a score onto a difficulty inside the profile's own bounds.

    Ascending: more points means harder problems. The old code inverted this,
    making the bot easier the better the child did.
    """
    profile = get_profile(profile_key)
    steps = max(0, score) // POINTS_PER_LEVEL
    return profile.clamp_difficulty(profile.min_difficulty + steps)


def clamp_score(score: int) -> int:
    return max(MIN_SCORE, min(MAX_SCORE, score))


async def load_progress(db: Database, user_id: int) -> UserProgress:
    row = await db.get_user(user_id)
    profile = (row["grade_profile"] if row else None) or ""
    score = int(row["score"]) if row and row["score"] is not None else 0
    difficulty = int(row["difficulty"]) if row and row["difficulty"] is not None else 1
    return UserProgress(profile=profile, difficulty=difficulty, score=score)


async def apply_answer_outcome(
    db: Database, user_id: int, correct: bool
) -> tuple[UserProgress, int | None]:
    """Move the score, recompute difficulty, and report any difficulty change.

    Returns the new progress and the previous difficulty when it changed, so the
    caller can tell the user and record an event.
    """
    before = await load_progress(db, user_id)
    score = clamp_score(before.score + (1 if correct else -1))
    difficulty = difficulty_for_score(score, before.profile)

    await db.set_user_fields(user_id, score=score, difficulty=difficulty)

    changed = difficulty if difficulty != before.difficulty else None
    if changed is not None:
        await db.record_event(
            user_id,
            "difficulty_change",
            {"from": before.difficulty, "to": difficulty, "score": score},
        )
        _LOGGER.info(
            "user %s difficulty %s -> %s (score %s)", user_id, before.difficulty, difficulty, score
        )

    return UserProgress(profile=before.profile, difficulty=difficulty, score=score), (
        before.difficulty if changed is not None else None
    )


async def issue_problem(state: FSMContext, progress: UserProgress) -> str:
    """Generate the next problem, store it, and return the message text."""
    problem = generate(progress.difficulty, progress.profile)
    await state.update_data(
        expression=problem.expression,
        answer=problem.answer,
        attempt=1,
        asked_at=time.time(),
        difficulty=problem.difficulty,
        profile=problem.profile,
    )
    return (
        "🔔 Новый примерчик! 🔔\n"
        f"<code>{html.escape(problem.expression)}</code>\n"
        "Пиши ответ! ⏱️"
    )


def parse_answer(raw: str) -> int | float | None:
    """Read a child's answer, tolerating spaces and a comma decimal separator."""
    cleaned = raw.strip().replace(" ", "").replace(" ", "").replace(",", ".")
    if not cleaned:
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return int(value) if value.is_integer() else value


def restate(expression: str) -> str:
    """Show the current problem again, escaped for HTML parse mode."""
    return f"Вот наш пример:\n<code>{html.escape(expression)}</code>"


def category_for_correct(attempt: int) -> str:
    return {
        1: texts.CORRECT_1ST,
        2: texts.CORRECT_2ND,
    }.get(attempt, texts.CORRECT_3RD)

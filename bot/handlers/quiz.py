"""The answer loop: three attempts per problem, then a new one either way.

One handler covers all three attempts. The old code had three near-identical
handlers, one per attempt, which is why every change had to be made three times.
"""

from __future__ import annotations

import html
import logging
import time

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot import quiz, texts
from bot.math.profiles import get_profile
from bot.services.phrase_service import PhraseService
from bot.states import UserStates
from bot.storage.db import Database

_LOGGER = logging.getLogger(__name__)


async def _celebrate(message: Message, phrases: PhraseService, category: str) -> None:
    """Send a lone emoji, which Telegram renders large and animates.

    Purely decorative, so a failure here must never interrupt the loop.
    """
    emoji = phrases.celebration(category)
    if not emoji:
        return
    try:
        await message.answer(emoji)
    except Exception as exc:  # noqa: BLE001 - decoration is never worth an error
        _LOGGER.info("could not send the celebration emoji: %s", exc)

async def answer_handler(
    message: Message,
    state: FSMContext,
    db: Database,
    phrases: PhraseService,
    session_id: int | None = None,
    max_input_length: int = 200,
) -> None:
    user = message.from_user
    if user is None:
        return

    raw = message.text or ""
    if len(raw) > max_input_length:
        await db.record_event(user.id, "oversized_input", {"length": len(raw)})
        await message.answer("Ого, какое длинное сообщение! Пришли, пожалуйста, просто число. 🙂")
        return

    data = await state.get_data()
    expression: str = data.get("expression", "")
    correct_answer: int = int(data.get("answer", 0))
    attempt: int = int(data.get("attempt", 1))
    asked_at: float = float(data.get("asked_at", time.time()))
    difficulty: int = int(data.get("difficulty", 1))
    profile_key: str = data.get("profile") or (await quiz.load_progress(db, user.id)).profile

    if not expression:
        # State was lost (Redis restart, or a stale chat). Start a fresh problem
        # rather than judging an answer to a problem nobody remembers.
        progress = await quiz.load_progress(db, user.id)
        await message.answer(await quiz.issue_problem(state, progress))
        return

    given = quiz.parse_answer(raw)
    ms_to_answer = int((time.time() - asked_at) * 1000)

    if given is None:
        phrase = await phrases.get(texts.INVALID_INPUT, user.id)
        await db.record_event(user.id, "invalid_input", {"text": raw[:64]})
        # An unparseable answer costs no attempt — it is a typo, not a mistake.
        await message.answer(f"{phrase.text}\n{quiz.restate(expression)}")
        return

    is_correct = given == correct_answer

    if is_correct:
        progress, previous_difficulty = await quiz.apply_answer_outcome(db, user.id, True)
        await db.record_attempt(
            user_id=user.id,
            session_id=session_id,
            expression=expression,
            correct_answer=correct_answer,
            given_answer=str(given),
            attempt_no=attempt,
            is_correct=True,
            difficulty=difficulty,
            grade_profile=profile_key or get_profile(None).key,
            score_after=progress.score,
            ms_to_answer=ms_to_answer,
        )
        category = quiz.category_for_correct(attempt)
        phrase = await phrases.get(category, user.id)
        await message.answer(phrase.text)
        await _celebrate(message, phrases, category)

        if previous_difficulty is not None and progress.difficulty > previous_difficulty:
            level_up = await phrases.get(texts.LEVEL_UP, user.id)
            await message.answer(f"{level_up.text} (сложность {progress.difficulty})")
            await _celebrate(message, phrases, texts.LEVEL_UP)

        await message.answer(await quiz.issue_problem(state, progress))
        return

    if attempt < quiz.MAX_ATTEMPTS:
        await db.record_attempt(
            user_id=user.id,
            session_id=session_id,
            expression=expression,
            correct_answer=correct_answer,
            given_answer=str(given),
            attempt_no=attempt,
            is_correct=False,
            difficulty=difficulty,
            grade_profile=profile_key or get_profile(None).key,
            score_after=(await quiz.load_progress(db, user.id)).score,
            ms_to_answer=ms_to_answer,
        )
        await state.update_data(attempt=attempt + 1, asked_at=time.time())
        phrase = await phrases.get(texts.WRONG_RETRY, user.id)
        await message.answer(f"{phrase.text}\n{quiz.restate(expression)}")
        return

    # Third attempt spent: reveal the answer, take a point, move on.
    progress, previous_difficulty = await quiz.apply_answer_outcome(db, user.id, False)
    await db.record_attempt(
        user_id=user.id,
        session_id=session_id,
        expression=expression,
        correct_answer=correct_answer,
        given_answer=str(given),
        attempt_no=attempt,
        is_correct=False,
        difficulty=difficulty,
        grade_profile=profile_key or get_profile(None).key,
        score_after=progress.score,
        ms_to_answer=ms_to_answer,
    )
    phrase = await phrases.get(texts.WRONG_FINAL, user.id)
    await message.answer(
        f"{phrase.text}\nПравильный ответ: <b>{correct_answer}</b>\n"
        f"Пример был: <code>{html.escape(expression)}</code>"
    )
    await message.answer(await quiz.issue_problem(state, progress))


def build_router() -> Router:
    router = Router(name="quiz")
    router.message.register(answer_handler, UserStates.awaiting_answer)
    return router

"""The answer loop, driven through the real dispatcher with no network.

Every test here feeds a synthetic `Update` into the dispatcher the production
bot builds, middlewares included, and reads what the bot tried to send.
"""

from __future__ import annotations

import time

import pytest

from bot.math.evaluator import evaluate_display
from bot.storage import queries
from tests.conftest import TEST_ADMIN_ID, TEST_USER_ID, make_message_update


async def _start_and_choose(harness, profile: str = "grade3") -> str:
    """Run the first-run flow and return the text of the first problem."""
    await harness.send("/start")
    replies = await harness.click(f"profile:{profile}")
    return replies[-1]


def _expression_of(text: str) -> str:
    return text.split("<code>")[1].split("</code>")[0]


async def _current_answer(harness) -> int:
    state = await harness.dispatcher.storage.get_data(
        harness.dispatcher.fsm.resolve_context(
            harness.bot, chat_id=TEST_USER_ID, user_id=TEST_USER_ID
        ).key
    )
    return int(state["answer"])


class TestFirstRun:
    async def test_new_user_is_asked_for_a_profile_before_any_problem(self, harness) -> None:
        replies = await harness.send("/start")
        assert any("Выбери" in reply for reply in replies)
        # No problem is issued until the profile is chosen.
        assert not any("<code>" in reply for reply in replies)

    async def test_choosing_a_profile_issues_the_first_problem(self, harness) -> None:
        problem = await _start_and_choose(harness)
        assert "<code>" in problem
        expression = _expression_of(problem)
        assert evaluate_display(expression) == await _current_answer(harness)

    async def test_the_choice_is_persisted_and_recorded(self, harness) -> None:
        await _start_and_choose(harness, "grade4")
        user = await harness.db.get_user(TEST_USER_ID)
        assert user is not None and user["grade_profile"] == "grade4"
        kinds = [event["kind"] for event in await queries.recent_events(harness.db, TEST_USER_ID)]
        assert "level_change" in kinds

    async def test_a_returning_user_is_not_asked_again(self, harness) -> None:
        await _start_and_choose(harness)
        replies = await harness.send("/start")
        assert not any("Выбери" in reply for reply in replies)
        assert any("<code>" in reply for reply in replies)


class TestAnswerLoop:
    async def test_correct_first_attempt_scores_and_moves_on(self, harness) -> None:
        await _start_and_choose(harness)
        answer = await _current_answer(harness)

        replies = await harness.send(str(answer))
        assert any("<code>" in reply for reply in replies), "a new problem must follow"

        user = await harness.db.get_user(TEST_USER_ID)
        assert user is not None and user["score"] == 1

        attempts = await queries.recent_attempts(harness.db, TEST_USER_ID)
        assert attempts[0]["is_correct"] == 1
        assert attempts[0]["attempt_no"] == 1
        assert attempts[0]["ms_to_answer"] is not None

    async def test_score_is_committed_before_the_next_problem_is_issued(self, harness) -> None:
        """The ordering guarantee the old fire-and-forget writes did not give.

        By the time the reply carrying the next problem exists, the score for
        the previous answer must already be in the database.
        """
        await _start_and_choose(harness)
        for expected_score in (1, 2, 3):
            answer = await _current_answer(harness)
            await harness.send(str(answer))
            user = await harness.db.get_user(TEST_USER_ID)
            assert user is not None and user["score"] == expected_score

    async def test_three_wrong_attempts_reveal_the_answer_and_cost_a_point(self, harness) -> None:
        await _start_and_choose(harness)
        answer = await _current_answer(harness)
        wrong = str(answer + 1)

        first = await harness.send(wrong)
        assert any("Вот наш пример" in reply for reply in first)
        second = await harness.send(wrong)
        assert any("Вот наш пример" in reply for reply in second)

        third = await harness.send(wrong)
        assert any(f"Правильный ответ: <b>{answer}</b>" in reply for reply in third)
        assert any("<code>" in reply for reply in third)

        user = await harness.db.get_user(TEST_USER_ID)
        # The score floor is zero, so a fresh user simply stays there.
        assert user is not None and user["score"] == 0

        attempts = await queries.recent_attempts(harness.db, TEST_USER_ID)
        assert [attempt["attempt_no"] for attempt in attempts[:3]] == [3, 2, 1]
        assert all(attempt["is_correct"] == 0 for attempt in attempts[:3])

    async def test_correct_on_the_third_attempt_still_scores(self, harness) -> None:
        await _start_and_choose(harness)
        answer = await _current_answer(harness)
        await harness.send(str(answer + 1))
        await harness.send(str(answer + 2))
        replies = await harness.send(str(answer))

        assert any("<code>" in reply for reply in replies)
        user = await harness.db.get_user(TEST_USER_ID)
        assert user is not None and user["score"] == 1

    async def test_non_numeric_input_does_not_consume_an_attempt(self, harness) -> None:
        await _start_and_choose(harness)
        answer = await _current_answer(harness)

        for _ in range(4):
            replies = await harness.send("не знаю")
            assert any("Вот наш пример" in reply for reply in replies)

        # Still on the first attempt: the correct answer must still be accepted.
        replies = await harness.send(str(answer))
        assert any("<code>" in reply for reply in replies)
        user = await harness.db.get_user(TEST_USER_ID)
        assert user is not None and user["score"] == 1

        kinds = [event["kind"] for event in await queries.recent_events(harness.db, TEST_USER_ID)]
        assert "invalid_input" in kinds

    @pytest.mark.parametrize("template", (" {} ", "{},0", " {}"))
    async def test_tolerated_numeric_formats(self, harness, template: str) -> None:
        await _start_and_choose(harness)
        answer = await _current_answer(harness)
        replies = await harness.send(template.format(answer))
        assert any("<code>" in reply for reply in replies)

    async def test_oversized_input_is_refused_without_being_judged(self, harness) -> None:
        await _start_and_choose(harness)
        replies = await harness.send("9" * 500)
        assert any("длинное сообщение" in reply for reply in replies)
        assert not await queries.recent_attempts(harness.db, TEST_USER_ID)

    async def test_angle_brackets_survive_a_round_trip(self, harness) -> None:
        """User text echoed back must be escaped, or Telegram rejects the message."""
        await _start_and_choose(harness)
        replies = await harness.send("<script>")
        assert replies
        assert not any("<script>" in reply for reply in replies)


class TestDifficulty:
    async def test_difficulty_rises_with_score_and_is_recorded(self, harness) -> None:
        await _start_and_choose(harness, "grade4")
        await harness.db.set_user_fields(TEST_USER_ID, score=9)

        answer = await _current_answer(harness)
        replies = await harness.send(str(answer))

        user = await harness.db.get_user(TEST_USER_ID)
        assert user is not None and user["difficulty"] == 2
        assert any("сложность 2" in reply for reply in replies)

        kinds = [event["kind"] for event in await queries.recent_events(harness.db, TEST_USER_ID)]
        assert "difficulty_change" in kinds

    async def test_difficulty_never_leaves_the_profile(self, harness) -> None:
        await _start_and_choose(harness, "grade3")
        await harness.db.set_user_fields(TEST_USER_ID, score=48)
        answer = await _current_answer(harness)
        await harness.send(str(answer))

        user = await harness.db.get_user(TEST_USER_ID)
        assert user is not None and user["difficulty"] == 4  # grade3 max


class TestLifecycle:
    async def test_stop_clears_state_but_keeps_history(self, harness) -> None:
        await _start_and_choose(harness)
        answer = await _current_answer(harness)
        await harness.send(str(answer))

        replies = await harness.send("/stop")
        assert replies

        session = await harness.db.fetch_one(
            "SELECT * FROM sessions WHERE user_id = ?", (TEST_USER_ID,)
        )
        assert session is not None and session["ended_at"] is not None
        assert await queries.recent_attempts(harness.db, TEST_USER_ID)

    async def test_lost_state_issues_a_fresh_problem_instead_of_judging(self, harness) -> None:
        await _start_and_choose(harness)
        context = harness.dispatcher.fsm.resolve_context(
            harness.bot, chat_id=TEST_USER_ID, user_id=TEST_USER_ID
        )
        await context.set_data({})

        replies = await harness.send("42")
        assert any("<code>" in reply for reply in replies)
        assert not await queries.recent_attempts(harness.db, TEST_USER_ID)

    async def test_unknown_text_outside_the_loop_gets_the_fallback(self, harness) -> None:
        replies = await harness.send("привет")
        assert any("/start" in reply for reply in replies)


class TestAccessControl:
    async def test_a_banned_user_is_ignored_entirely(self, harness) -> None:
        await harness.db.set_ban(TEST_USER_ID, True, by_admin=1, reason="тест")
        harness.dispatcher["ban_middleware"].invalidate()

        assert await harness.send("/start") == []
        assert await harness.db.get_user(TEST_USER_ID) is not None

    async def test_a_flood_is_throttled_and_recorded(self, harness) -> None:
        await _start_and_choose(harness)
        harness.dispatcher["throttle_middleware"].configure(messages=5, window=3.0)
        harness.session.clear()

        replied = 0
        for _ in range(12):
            if await harness.send("1"):
                replied += 1
        assert replied < 12

        kinds = [event["kind"] for event in await queries.recent_events(harness.db, TEST_USER_ID)]
        assert "throttled" in kinds


class TestAdminCommands:
    async def test_admin_sees_statistics(self, harness) -> None:
        await _start_and_choose(harness)
        replies = await harness.send("/stats", user_id=TEST_ADMIN_ID)
        assert any("Статистика" in reply for reply in replies)

    async def test_non_admin_gets_only_the_fallback(self, harness) -> None:
        replies = await harness.send("/stats", user_id=TEST_USER_ID)
        assert replies
        assert not any("Статистика" in reply for reply in replies)
        assert any("/start" in reply for reply in replies)

    async def test_admin_can_ban_and_unban(self, harness) -> None:
        await harness.send(f"/ban {TEST_USER_ID} флуд", user_id=TEST_ADMIN_ID)
        assert await harness.db.is_banned(TEST_USER_ID) is True
        assert await harness.send("/start") == []

        await harness.send(f"/unban {TEST_USER_ID}", user_id=TEST_ADMIN_ID)
        assert await harness.db.is_banned(TEST_USER_ID) is False
        assert await harness.send("/start") != []

    async def test_user_card_reports_recorded_answers(self, harness) -> None:
        await _start_and_choose(harness)
        answer = await _current_answer(harness)
        await harness.send(str(answer))

        replies = await harness.send(f"/user {TEST_USER_ID}", user_id=TEST_ADMIN_ID)
        assert any("Последние ответы" in reply for reply in replies)

    async def test_health_reports_technical_state(self, harness) -> None:
        replies = await harness.send("/health", user_id=TEST_ADMIN_ID)
        assert any("аптайм" in reply for reply in replies)

"""The phrase pool: what handlers get, and what the worker does out of sight."""

from __future__ import annotations

import pytest

from bot.services.phrase_service import STATIC_PROVIDER, PhraseService
from bot.services.validation import count_emoji, validate_phrase
from bot.storage import phrases as phrase_store
from bot.storage.db import Database
from bot.texts import CATEGORIES, STATIC_PHRASES
from tests.conftest import StubLLM

GOOD_LINES = [
    "Молодец! У тебя получилось! 🎉",
    "Вот это да, здорово справился! 🌟",
    "Так держать, ты растёшь на глазах!",
    "Ух ты, как быстро! 🚀",
    "Отлично, продолжаем в том же духе!",
]


class TestValidator:
    @pytest.mark.parametrize("text", GOOD_LINES)
    def test_accepts_ordinary_praise(self, text: str) -> None:
        assert validate_phrase(text, max_length=160, max_emoji=4)

    @pytest.mark.parametrize(
        "text,reason",
        [
            ("Смотри тут https://example.com", "link"),
            ("Загляни на evil.ru скорее", "link"),
            ("Ура <b>молодец</b>", "markup"),
            ("Отлично! {здорово}", "markup"),
            ("Great job, kid!", "latin"),
            ("Ответ 12 + 3 верный", "arithmetic"),
            ("Ты набрал 100 баллов", "multi-digit"),
            ("Ура! 🎉🎈🥇🌟🚀🎆", "emoji"),
            ("", "empty"),
            ("Первая строка\nвторая", "newline"),
            ("Nice!", "no russian"),
        ],
    )
    def test_rejects_unsuitable_output(self, text: str, reason: str) -> None:
        verdict = validate_phrase(text, max_length=160, max_emoji=4)
        assert not verdict, f"{reason}: {text!r} should have been rejected"
        assert verdict.reason

    def test_rejects_anything_too_long(self) -> None:
        assert not validate_phrase("Молодец! " * 40, max_length=160, max_emoji=4)

    def test_counts_distinct_emoji_separately(self) -> None:
        assert count_emoji("🎉🎈🥇") == 3
        assert count_emoji("👨‍👩‍👧") == 1
        assert count_emoji("Ура! ⚡️ Класс!") == 1


class TestSelection:
    async def test_empty_pool_falls_back_to_static_text(self, db: Database) -> None:
        service = PhraseService(db, None, target=3)
        phrase = await service.get("correct_1st", user_id=1)
        assert phrase.source == STATIC_PROVIDER
        assert phrase.text in STATIC_PHRASES["correct_1st"]

    async def test_every_category_has_a_static_fallback(self, db: Database) -> None:
        service = PhraseService(db, None, target=3)
        for category in CATEGORIES:
            phrase = await service.get(category, user_id=1)
            assert phrase.text

    async def test_pooled_phrases_are_preferred_and_marked_used(self, db: Database) -> None:
        await phrase_store.add_phrase(db, "correct_1st", "Из пула!", "stub", "m")
        service = PhraseService(db, None, target=3)

        phrase = await service.get("correct_1st", user_id=1)
        assert phrase.text == "Из пула!"
        assert phrase.source == "stub"
        assert await phrase_store.unseen_count(db, "correct_1st", user_id=1) == 0
        # Untouched for anybody else.
        assert await phrase_store.unseen_count(db, "correct_1st", user_id=2) == 1

    async def test_serving_queues_a_refill_without_awaiting_anything(
        self, db: Database
    ) -> None:
        llm = StubLLM(GOOD_LINES)
        service = PhraseService(db, llm, target=3)

        await service.get("correct_1st", user_id=1)
        # The read path must not have called the model.
        assert llm.calls == 0
        assert "correct_1st" in service._queued


class TestRefill:
    async def test_refill_stores_only_valid_lines(self, db: Database) -> None:
        llm = StubLLM(GOOD_LINES + ["Bad latin line", "Смотри https://evil.ru", "Ответ 2 + 2"])
        service = PhraseService(db, llm, target=5, retries=1)

        added = await service.refill("correct_1st")
        assert added == 5
        stored = [row["text"] for row in await phrase_store.phrases_in_category(db, "correct_1st")]
        assert set(stored) == set(GOOD_LINES)

    async def test_refill_survives_an_unavailable_provider(self, db: Database) -> None:
        service = PhraseService(db, StubLLM(fail=True), target=5, retries=2)
        assert await service.refill("correct_1st") == 0
        # And the bot still speaks.
        assert (await service.get("correct_1st", user_id=1)).source == STATIC_PROVIDER

    async def test_refill_respects_the_cap(self, db: Database) -> None:
        for index in range(12):
            await phrase_store.add_phrase(db, "correct_1st", f"старая {index}", "stub", "m")
        service = PhraseService(db, StubLLM(GOOD_LINES), target=14, cap=8, retries=1)

        await service.refill("correct_1st")
        assert await phrase_store.usable_count(db, "correct_1st") == 8

    async def test_disabled_phrases_become_negative_examples(self, db: Database) -> None:
        phrase_id = await phrase_store.add_phrase(db, "correct_1st", "забракованная", "stub", "m")
        assert phrase_id is not None
        await phrase_store.set_disabled(db, phrase_id, True, by_admin=1)

        class CapturingLLM(StubLLM):
            prompt = ""

            async def complete(self, system, user, **kwargs):
                CapturingLLM.prompt = user
                return await super().complete(system, user, **kwargs)

        service = PhraseService(db, CapturingLLM(GOOD_LINES), target=3, retries=1)
        await service.refill("correct_1st")
        assert "забракованная" in CapturingLLM.prompt

    async def test_unknown_category_is_ignored(self, db: Database) -> None:
        service = PhraseService(db, StubLLM(GOOD_LINES), target=3)
        assert await service.refill("no_such_category") == 0

    async def test_worker_drains_the_queue(self, db: Database) -> None:
        service = PhraseService(db, StubLLM(GOOD_LINES), target=2, retries=1)
        await service.start()
        try:
            await service._queue.join()
        finally:
            await service.stop()
        assert await phrase_store.usable_count(db, "correct_1st") >= 2


class TestParsing:
    def test_strips_list_decoration_and_quotes(self) -> None:
        raw = '1. "Молодец!"\n- Отлично!\n* «Здорово!»\n\n  Так держать!  '
        assert PhraseService._parse(raw) == [
            "Молодец!",
            "Отлично!",
            "Здорово!",
            "Так держать!",
        ]


class TestCelebration:
    """A lone emoji renders large in Telegram and animates; it must never fail."""

    def test_celebratory_categories_offer_an_emoji(self, tmp_path) -> None:
        from bot.texts import CORRECT_1ST, CORRECT_2ND, CORRECT_3RD, LEVEL_UP

        service = PhraseService(None, None)  # type: ignore[arg-type]
        for category in (CORRECT_1ST, CORRECT_2ND, CORRECT_3RD, LEVEL_UP):
            emoji = service.celebration(category)
            assert emoji and len(emoji) <= 2

    def test_consoling_categories_get_no_emoji(self) -> None:
        from bot.texts import INVALID_INPUT, WRONG_FINAL, WRONG_RETRY

        service = PhraseService(None, None)  # type: ignore[arg-type]
        for category in (WRONG_RETRY, WRONG_FINAL, INVALID_INPUT):
            assert service.celebration(category) is None

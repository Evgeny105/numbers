"""The phrase pool: what the handlers ask for, and what refills it.

Two halves that never block each other.

The read half is a single indexed query. A handler asks for a phrase, gets one
back, and replies. If the pool is empty it gets a static phrase compiled into
the source. It never awaits an LLM, so a language model being slow, absent or
broken cannot make a child wait or see an error.

The write half is a background worker draining a queue. It tops each category up
to its target and trims it back from its cap. Everything that can go wrong with
a network call goes wrong here, out of sight of the user.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass

from bot.services.llm import Completion, LLMClient, LLMUnavailable
from bot.services.validation import validate_phrase
from bot.storage import phrases as phrase_store
from bot.storage.db import Database
from bot.texts import CATEGORIES, CELEBRATION_EMOJI, STATIC_PHRASES

_LOGGER = logging.getLogger(__name__)

STATIC_PROVIDER = "static"

_SYSTEM_PROMPT = (
    "Ты придумываешь короткие реплики для телеграм-бота, который помогает "
    "ребёнку 9-10 лет тренировать устный счёт. Реплики читает ребёнок. "
    "Пиши по-русски, тепло и весело, без сюсюканья и без нравоучений. "
    "Каждая реплика — одна строка длиной до {max_length} символов. "
    "Эмодзи приветствуются: ставь 2-4 штуки в реплике, но не больше {max_emoji}. "
    "Категорически нельзя: ссылки, любые теги и угловые скобки, латинские слова, "
    "числа длиннее одной цифры, примеры и знаки арифметики. "
    "Верни ровно {count} реплик, каждую с новой строки, без нумерации и без кавычек."
)


@dataclass(frozen=True)
class Phrase:
    """A phrase ready to send, and where it came from."""

    text: str
    source: str
    phrase_id: int | None = None


class PhraseService:
    """Serves phrases to handlers and keeps the pool stocked in the background."""

    def __init__(
        self,
        db: Database,
        llm: LLMClient | None,
        *,
        target: int = 10,
        cap: int = 40,
        max_length: int = 160,
        max_emoji: int = 4,
        retries: int = 3,
        rng: random.Random | None = None,
    ) -> None:
        self._db = db
        self._llm = llm
        self._target = target
        self._cap = cap
        self._max_length = max_length
        self._max_emoji = max_emoji
        self._retries = retries
        self._rng = rng or random
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._queued: set[str] = set()
        self._worker: asyncio.Task[None] | None = None

    # -- the read half -----------------------------------------------------

    async def get(self, category: str, user_id: int) -> Phrase:
        """A phrase for this user, right now. Never awaits a network call."""
        stored = await phrase_store.pick_for_user(self._db, category, user_id)
        if stored is not None:
            await phrase_store.mark_used(self._db, stored.id, user_id)
            unseen = await phrase_store.unseen_count(self._db, category, user_id)
            if unseen < self._target:
                self.request_refill(category)
            return Phrase(text=stored.text, source=stored.provider, phrase_id=stored.id)

        self.request_refill(category)
        return Phrase(text=self.static(category), source=STATIC_PROVIDER)

    def celebration(self, category: str) -> str | None:
        """A single emoji to send as its own message, or None for this category.

        Telegram renders a lone emoji large and animates it, so this is a
        cheap bit of delight that costs no tokens and cannot fail.
        """
        options = CELEBRATION_EMOJI.get(category)
        return self._rng.choice(list(options)) if options else None

    def static(self, category: str) -> str:
        """The compiled-in fallback for a category."""
        options = STATIC_PHRASES.get(category)
        if not options:
            return "Продолжаем! 🙂"
        return self._rng.choice(list(options))

    # -- the write half ----------------------------------------------------

    def request_refill(self, category: str) -> None:
        """Queue a category for topping up. Cheap, synchronous, idempotent."""
        if category in self._queued:
            return
        self._queued.add(category)
        self._queue.put_nowait(category)

    async def start(self) -> None:
        """Start the worker and queue an initial fill for every category."""
        if self._worker is not None:
            return
        self._worker = asyncio.create_task(self._run(), name="phrase-refill-worker")
        for category in CATEGORIES:
            if await phrase_store.usable_count(self._db, category) < self._target:
                self.request_refill(category)

    async def stop(self) -> None:
        if self._worker is None:
            return
        self._worker.cancel()
        try:
            await self._worker
        except asyncio.CancelledError:
            pass
        self._worker = None

    async def _run(self) -> None:
        while True:
            category = await self._queue.get()
            try:
                await self.refill(category)
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - the worker must never die
                _LOGGER.exception("phrase refill failed for category %s", category)
            finally:
                self._queued.discard(category)
                self._queue.task_done()

    async def refill(self, category: str) -> int:
        """Top one category up to its target. Returns how many were added."""
        if category not in CATEGORIES:
            _LOGGER.warning("refill requested for unknown category %s", category)
            return 0
        if self._llm is None:
            return 0

        added = 0
        for _ in range(self._retries):
            missing = self._target - await phrase_store.usable_count(self._db, category)
            if missing <= 0:
                break
            try:
                completion = await self._generate(category, missing)
            except LLMUnavailable as exc:
                _LOGGER.info("no phrases generated for %s: %s", category, exc)
                break
            for text in self._parse(completion.text):
                verdict = validate_phrase(
                    text, max_length=self._max_length, max_emoji=self._max_emoji
                )
                if not verdict:
                    _LOGGER.debug("rejected phrase for %s (%s): %r", category, verdict.reason, text)
                    continue
                stored_id = await phrase_store.add_phrase(
                    self._db, category, text.strip(), completion.provider, completion.model
                )
                if stored_id is not None:
                    added += 1

        if added:
            evicted = await phrase_store.evict_over_cap(self._db, category, self._cap)
            _LOGGER.info(
                "phrase pool %s: +%d, -%d, now %d",
                category,
                added,
                evicted,
                await phrase_store.usable_count(self._db, category),
            )
        return added

    async def _generate(self, category: str, count: int) -> Completion:
        assert self._llm is not None
        brief = CATEGORIES[category].brief
        existing = await phrase_store.existing_texts(self._db, category)
        rejected = await phrase_store.disabled_texts(self._db, category)

        parts = [f"Нужны реплики для случая: {brief}."]
        if existing:
            parts.append(
                "Такие реплики уже есть, придумай другие:\n"
                + "\n".join(f"- {text}" for text in existing[:15])
            )
        if rejected:
            parts.append(
                "А такие реплики были забракованы, не повторяй их и не пиши похожие:\n"
                + "\n".join(f"- {text}" for text in rejected[:10])
            )

        system = _SYSTEM_PROMPT.format(
            max_length=self._max_length, max_emoji=self._max_emoji, count=count
        )
        return await self._llm.complete(
            system,
            "\n\n".join(parts),
            temperature=1.1,
            max_tokens=120 * count + 100,
        )

    @staticmethod
    def _parse(raw: str) -> list[str]:
        """Split a completion into candidate phrases, stripping list decoration."""
        candidates: list[str] = []
        for line in raw.splitlines():
            text = line.strip()
            if not text:
                continue
            # Models like to number their lists however they are asked not to.
            text = text.lstrip("-•*0123456789.) \t")
            text = text.strip().strip('"').strip("«»").strip()
            if text:
                candidates.append(text)
        return candidates

"""Per-user rate limiting.

The bot is open to anyone who finds it, so a flood has to cost the sender
nothing but achieve nothing. Excess messages are dropped silently — an error
reply would itself be traffic — and recorded as events so the admin surface
shows who is hammering it.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from bot.storage.db import Database

_LOGGER = logging.getLogger(__name__)

#: Do not write an event for every dropped message of a burst; one per this many
#: seconds per user is enough to see the pattern without flooding the table.
_EVENT_COOLDOWN = 60.0


class ThrottleMiddleware(BaseMiddleware):
    def __init__(self, db: Database, messages: int = 5, window: float = 3.0) -> None:
        self._db = db
        self._messages = messages
        self._window = window
        self._hits: dict[int, deque[float]] = {}
        self._last_event: dict[int, float] = {}

    def configure(self, messages: int, window: float) -> None:
        """Change the limit at runtime; used by tests and by the admin surface."""
        self._messages = messages
        self._window = window
        self._hits.clear()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        now = time.monotonic()
        hits = self._hits.setdefault(user.id, deque())
        while hits and now - hits[0] > self._window:
            hits.popleft()

        if len(hits) >= self._messages:
            wall = time.time()
            if wall - self._last_event.get(user.id, 0.0) > _EVENT_COOLDOWN:
                self._last_event[user.id] = wall
                await self._db.record_event(
                    user.id,
                    "throttled",
                    {"messages": self._messages, "window_seconds": self._window},
                )
            _LOGGER.info("throttled user %s", user.id)
            return None

        hits.append(now)
        return await handler(event, data)

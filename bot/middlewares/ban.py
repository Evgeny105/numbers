"""Drop everything from a banned user, before any handler sees it.

The ban list lives in the database so it survives restarts. It is cached in
memory because it is read on every single update and changes about once a year;
the cache is invalidated explicitly by the admin handler that changes a ban.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from bot.storage.db import Database

_LOGGER = logging.getLogger(__name__)


class BanMiddleware(BaseMiddleware):
    def __init__(self, db: Database) -> None:
        self._db = db
        self._banned: set[int] | None = None

    async def _banned_ids(self) -> set[int]:
        if self._banned is None:
            rows = await self._db.fetch_all("SELECT user_id FROM users WHERE banned = 1")
            self._banned = {int(row["user_id"]) for row in rows}
        return self._banned

    def invalidate(self) -> None:
        """Called after a ban changes, so the next update sees it."""
        self._banned = None

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is not None and user.id in await self._banned_ids():
            _LOGGER.info("ignored update from banned user %s", user.id)
            return None
        return await handler(event, data)

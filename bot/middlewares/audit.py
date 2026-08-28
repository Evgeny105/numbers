"""Register the user and attach shared services to every handler call.

This runs before every handler, so a handler never has to think about whether
the user exists in the database or which session their answer belongs to.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from bot.logging_setup import current_user_id
from bot.storage.db import Database


_LOGGER = logging.getLogger(__name__)


class AuditMiddleware(BaseMiddleware):
    def __init__(self, db: Database, idle_timeout: float) -> None:
        self._db = db
        self._idle_timeout = idle_timeout

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is None or user.is_bot:
            return await handler(event, data)

        token = current_user_id.set(user.id)
        try:
            record = await self._db.upsert_user(user.id, user.username, user.full_name)
            data["user_record"] = record
            data["session_id"] = await self._db.ensure_session(user.id, self._idle_timeout)
            _LOGGER.debug(
                "update from %s (@%s) session=%s",
                user.full_name,
                user.username or "-",
                data["session_id"],
            )
            return await handler(event, data)
        finally:
            current_user_id.reset(token)

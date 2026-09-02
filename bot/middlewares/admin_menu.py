"""Give an administrator their menu the first time they say something.

`setMyCommands` with a chat scope is refused for a chat the bot has never
received a message from, which is exactly the state a newly configured
administrator is in at startup. Waiting for the next deploy to fix that is a
poor answer, so the first message from an administrator triggers one attempt.

Once per administrator per process: the sync is a read plus, at most, a write,
and doing it on every message would put two extra API calls in front of every
`/stats`.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from bot.profile import BotProfile, sync_admin_menu

_LOGGER = logging.getLogger(__name__)


class AdminMenuMiddleware(BaseMiddleware):
    def __init__(self, profile: BotProfile, admin_ids: frozenset[int]) -> None:
        self._profile = profile
        self._admin_ids = admin_ids
        self._synced: set[int] = set()

    def mark_synced(self, admin_id: int) -> None:
        """Called after a successful startup sync, so it is not repeated."""
        self._synced.add(admin_id)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is not None and user.id in self._admin_ids and user.id not in self._synced:
            self._synced.add(user.id)
            bot = data.get("bot")
            if bot is not None:
                try:
                    await sync_admin_menu(bot, user.id, self._profile)
                except Exception as exc:  # noqa: BLE001 - a menu is never worth an error
                    _LOGGER.info("could not sync the admin menu for %s: %s", user.id, exc)
        return await handler(event, data)

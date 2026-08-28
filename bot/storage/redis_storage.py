"""FSM storage selection: Redis when it is reachable, memory when it is not.

Falling back to memory keeps the bot usable during a Redis outage. The cost is
that an in-flight problem is forgotten on restart — acceptable, because the
history that matters is in SQLite either way.
"""

from __future__ import annotations

import logging

from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

_LOGGER = logging.getLogger(__name__)


async def build_storage(redis_url: str) -> BaseStorage:
    """Return a working FSM storage, preferring Redis."""
    if not redis_url:
        _LOGGER.warning("no Redis URL configured; using in-memory FSM storage")
        return MemoryStorage()
    try:
        storage = RedisStorage.from_url(redis_url)
        await storage.redis.ping()
    except Exception as exc:  # noqa: BLE001 - any Redis failure means fall back
        _LOGGER.error("Redis at %s is unavailable (%s); using in-memory FSM storage", redis_url, exc)
        return MemoryStorage()
    _LOGGER.info("FSM state stored in Redis at %s", redis_url)
    return storage

import logging
from os import getenv

from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.redis import RedisStorage

_LOGGER = logging.getLogger(__name__)


def init_redis() -> RedisStorage:
    redis_urls = getenv("REDIS").split(",")
    if len(redis_urls) == 0:
        _LOGGER.error("REDIS environment variable is not set")
        raise ValueError("REDIS environment variable is not set")
    elif len(redis_urls) == 1:
        _LOGGER.info("REDIS environment variable is set to a single URL")
        full_url = f"redis://{redis_urls[0]}"
        _LOGGER.info(f"Trying to connect to Redis at {full_url}")
        storage = RedisStorage.from_url(full_url)
        return storage
    else:
        _LOGGER.error("REDIS environment variable is set to multiple URLs")
        raise ValueError("REDIS environment variable is set to multiple URLs")

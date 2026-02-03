"""
Модуль для инициализации и конфигурации Redis хранилища.

Предоставляет функцию для создания RedisStorage с поддержкой
единственного URL подключения и автоматической обработкой ошибок.
"""

import logging
from os import getenv

from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.redis import RedisStorage

_LOGGER = logging.getLogger(__name__)


def init_redis() -> RedisStorage:
    """
    Инициализирует Redis хранилище для FSM (Finite State Machine).

    Читает URL подключения из переменной окружения REDIS и создаёт
    экземпляр RedisStorage. Поддерживается только одиночный URL подключения.

    Environment Variables:
        REDIS: URL подключения к Redis в формате "host:port" или "redis://host:port"

    Returns:
        RedisStorage: Инициализированное хранилище Redis для FSM

    Raises:
        ValueError: Если переменная окружения REDIS не задана или содержит несколько URL
        ConnectionError: Если не удаётся подключиться к Redis (поднимается aiogram)

    Examples:
        >>> # В .env файле: REDIS=localhost:6379
        >>> storage = init_redis()
        >>> type(storage)
        <class 'aiogram.fsm.storage.redis.RedisStorage'>

        >>> # Также поддерживается полный URL
        >>> # REDIS=redis://localhost:6379/0
        >>> storage = init_redis()

    Note:
        - Поддерживается только один URL подключения к Redis
        - При наличии нескольких URL (через запятую) будет выброшено исключение
        - Для отказоустойчивости рекомендуется использовать Redis Sentinel или Cluster
          (требует отдельной конфигурации)
    """
    redis_env: str | None = getenv("REDIS")
    if not redis_env:
        _LOGGER.error("REDIS environment variable is not set")
        raise ValueError("REDIS environment variable is not set")

    redis_urls: list[str] = redis_env.split(",")

    # Проверка: переменная окружения не задана
    if not redis_urls[0]:
        _LOGGER.error("REDIS environment variable is not set")
        raise ValueError("REDIS environment variable is not set")

    # Случай 1: Одиночный URL (основной сценарий использования)
    elif len(redis_urls) == 1:
        _LOGGER.info("REDIS environment variable is set to a single URL")

        # Формируем полный URL с протоколом redis:// если он отсутствует
        redis_url: str = redis_urls[0].strip()
        if not redis_url.startswith("redis://"):
            redis_url = f"redis://{redis_url}"

        _LOGGER.info(f"Trying to connect to Redis at {redis_url}")

        try:
            storage: RedisStorage = RedisStorage.from_url(redis_url)
            _LOGGER.info("Successfully initialized Redis storage")
            return storage
        except Exception as e:
            _LOGGER.error(f"Failed to connect to Redis: {e}")
            raise

    # Случай 2: Несколько URL (не поддерживается)
    else:
        _LOGGER.error(
            f"REDIS environment variable is set to {len(redis_urls)} URLs. "
            "Multiple Redis URLs are not supported. Please provide a single Redis URL."
        )
        raise ValueError(
            "REDIS environment variable is set to multiple URLs. "
            "Only single Redis URL is supported."
        )

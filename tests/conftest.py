"""Test fixtures: a real dispatcher, a fake Telegram, a temporary database.

The handler tests drive the *actual* dispatcher — the same middlewares, routers
and filters the deployed bot runs — with only the outbound HTTP session
replaced. That way a test can fail for the reasons production would fail, while
never touching the network.
"""

from __future__ import annotations

import itertools
import time
from datetime import datetime
from typing import Any

import pytest
import pytest_asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import TelegramMethod
from aiogram.types import Chat, Message, Update, User

from bot.config import Settings
from bot.services.openrouter import OpenRouterService
from bot.services.phrase_service import PhraseService
from bot.storage.db import Database

TEST_USER_ID = 500_100
TEST_ADMIN_ID = 900_900
TEST_CHAT_ID = TEST_USER_ID

_update_ids = itertools.count(1)
_message_ids = itertools.count(1)


class RecordingSession(BaseSession):
    """A Telegram session that records outgoing calls instead of sending them."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []

    @property
    def texts(self) -> list[str]:
        return [
            str(getattr(request, "text", ""))
            for request in self.requests
            if getattr(request, "text", None)
        ]

    def clear(self) -> None:
        self.requests.clear()

    async def close(self) -> None:  # pragma: no cover - nothing to close
        pass

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None):
        self.requests.append(method)
        name = type(method).__name__
        if name in ("SendMessage", "EditMessageText"):
            return Message(
                message_id=next(_message_ids),
                date=datetime.now(),
                chat=Chat(id=getattr(method, "chat_id", TEST_CHAT_ID), type="private"),
                from_user=User(id=1, is_bot=True, first_name="Bot"),
                text=getattr(method, "text", ""),
            )
        if name == "GetMe":
            return User(id=1, is_bot=True, first_name="Bot", username="test_bot")
        return True

    async def stream_content(self, *args: Any, **kwargs: Any):  # pragma: no cover
        raise NotImplementedError
        yield b""


def make_message_update(
    text: str, user_id: int = TEST_USER_ID, full_name: str = "Тест Тестов"
) -> Update:
    """A synthetic private-chat text message, as Telegram would deliver it."""
    user = User(id=user_id, is_bot=False, first_name=full_name, username="tester")
    chat = Chat(id=user_id, type="private")
    message = Message(
        message_id=next(_message_ids),
        date=datetime.now(),
        chat=chat,
        from_user=user,
        text=text,
    )
    return Update(update_id=next(_update_ids), message=message)


def make_callback_update(data: str, user_id: int = TEST_USER_ID) -> Update:
    from aiogram.types import CallbackQuery

    user = User(id=user_id, is_bot=False, first_name="Тест Тестов", username="tester")
    chat = Chat(id=user_id, type="private")
    message = Message(
        message_id=next(_message_ids),
        date=datetime.now(),
        chat=chat,
        from_user=User(id=1, is_bot=True, first_name="Bot"),
        text="Выбери уровень",
    )
    callback = CallbackQuery(
        id=str(next(_update_ids)),
        from_user=user,
        chat_instance="test",
        message=message,
        data=data,
    )
    return Update(update_id=next(_update_ids), callback_query=callback)


class StubLLM:
    """Stands in for `LLMClient`, with no network anywhere near it."""

    def __init__(self, lines: list[str] | None = None, fail: bool = False) -> None:
        self.lines = lines or []
        self.fail = fail
        self.calls = 0

    async def complete(self, system: str, user: str, **kwargs: Any):
        from bot.services.llm import Completion, LLMUnavailable

        self.calls += 1
        if self.fail:
            raise LLMUnavailable("stubbed failure")
        return Completion(text="\n".join(self.lines), provider="stub", model="stub-model")

    async def close(self) -> None:
        pass


def make_settings(db_path: str, **overrides: Any) -> Settings:
    """Settings for tests, with nothing that could reach the network."""
    defaults: dict[str, Any] = dict(
        bot_token="123456:TESTTOKEN",
        redis_url="",
        db_path=db_path,
        admin_ids=frozenset({TEST_ADMIN_ID}),
        http_proxy_url="",
        log_level="WARNING",
        llm_api_key="",
        lmstudio_base_url="",
        lmstudio_model="",
        lmstudio_timeout=1.0,
        openrouter_base_url="",
        openrouter_model="",
        openrouter_timeout=1.0,
        phrase_pool_target=3,
        phrase_pool_max=10,
        phrase_max_length=160,
        phrase_max_emoji=4,
        phrase_generate_retries=1,
        # Generous by default: only the throttling test wants to hit the limit.
        throttle_messages=100,
        throttle_window_seconds=3.0,
        max_input_length=200,
        session_idle_timeout_seconds=1800,
        admin_web_user="admin",
        admin_web_password="secret",
        balance_cache_seconds=300,
    )
    defaults.update(overrides)
    from pathlib import Path

    defaults["db_path"] = Path(defaults["db_path"])
    return Settings(**defaults)


@pytest_asyncio.fixture
async def db(tmp_path):
    database = await Database(tmp_path / "test.sqlite3").connect()
    try:
        yield database
    finally:
        await database.close()


@pytest.fixture
def settings(tmp_path):
    return make_settings(str(tmp_path / "test.sqlite3"))


@pytest_asyncio.fixture
async def phrases(db):
    service = PhraseService(db, None, target=3, cap=10)
    return service


@pytest_asyncio.fixture
async def harness(db, settings, phrases):
    """A dispatcher, a bot with a recording session, and the shared services."""
    from bot.__main__ import build_dispatcher

    session = RecordingSession()
    bot = Bot(settings.bot_token, session=session)
    openrouter = OpenRouterService("", cache_seconds=1)
    dispatcher = build_dispatcher(
        settings, db, phrases, openrouter, MemoryStorage(), time.time()
    )

    class Harness:
        def __init__(self) -> None:
            self.bot = bot
            self.dispatcher: Dispatcher = dispatcher
            self.session = session
            self.db = db
            self.phrases = phrases

        async def feed(self, update: Update) -> list[str]:
            self.session.clear()
            await self.dispatcher.feed_update(self.bot, update)
            return self.session.texts

        async def send(self, text: str, user_id: int = TEST_USER_ID) -> list[str]:
            return await self.feed(make_message_update(text, user_id))

        async def click(self, data: str, user_id: int = TEST_USER_ID) -> list[str]:
            return await self.feed(make_callback_update(data, user_id))

    try:
        yield Harness()
    finally:
        await bot.session.close()

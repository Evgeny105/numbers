"""End-to-end harness: drive the bot for real, with nobody touching Telegram.

Follows the pattern proven in a sibling bot project by the same author. It builds a
synthetic `Update` and feeds it through the application's real `Dispatcher`,
with a real `Bot` — so middlewares, handlers and storage all run exactly as they
do in production, and every reply is a genuine Telegram Bot API call landing in
a real chat.

`scenario` mode plays a whole session and checks each reply against a pattern,
exiting non-zero on the first mismatch. That is the post-deploy smoke check: one
command, no human, a usable exit code.

Usage:
    uv run python -m tools.e2e_client fetch-chat-id
    uv run python -m tools.e2e_client send /start --chat-id <id>
    uv run python -m tools.e2e_client scenario --chat-id <id>
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from bot.__main__ import build_bot, build_dispatcher
from bot.config import Settings
from bot.logging_setup import setup_logging
from bot.math.evaluator import evaluate_display
from bot.services.llm import LLMClient, build_providers
from bot.services.openrouter import OpenRouterService
from bot.services.phrase_service import PhraseService
from bot.storage.db import Database
from bot.storage.redis_storage import build_storage

_LOGGER = logging.getLogger("e2e")

_update_ids = itertools.count(900_000_000)
_message_ids = itertools.count(700_000)


@dataclass
class Runtime:
    """Everything the harness needs, torn down together."""

    settings: Settings
    bot: Bot
    dispatcher: Dispatcher
    db: Database
    llm: LLMClient
    phrases: PhraseService
    sent: list[str] = field(default_factory=list)

    async def close(self) -> None:
        await self.phrases.stop()
        await self.llm.close()
        await self.db.close()
        await self.bot.session.close()


class Recorder:
    """Wraps the bot session so replies are both delivered and captured."""

    def __init__(self, bot: Bot, sink: list[str]) -> None:
        self._inner = bot.session.make_request
        self._sink = sink
        bot.session.make_request = self._make_request  # type: ignore[method-assign]

    async def _make_request(self, bot: Bot, method: Any, timeout: int | None = None) -> Any:
        text = getattr(method, "text", None)
        if text:
            self._sink.append(str(text))
        return await self._inner(bot, method, timeout=timeout)


async def build_runtime() -> Runtime:
    settings = Settings.from_env()
    setup_logging(settings.log_level, settings.db_path, name="e2e.log")

    db = await Database(settings.db_path).connect()
    storage = await build_storage(settings.redis_url)
    llm = LLMClient(build_providers(settings))
    phrases = PhraseService(
        db,
        llm,
        target=settings.phrase_pool_target,
        cap=settings.phrase_pool_max,
        max_length=settings.phrase_max_length,
        max_emoji=settings.phrase_max_emoji,
        retries=settings.phrase_generate_retries,
    )
    openrouter = OpenRouterService(
        settings.llm_api_key,
        settings.openrouter_base_url,
        settings.http_proxy_url or None,
        settings.balance_cache_seconds,
    )
    bot = build_bot(settings)
    dispatcher = build_dispatcher(settings, db, phrases, openrouter, storage, time.time())

    runtime = Runtime(settings, bot, dispatcher, db, llm, phrases)
    Recorder(bot, runtime.sent)
    return runtime


def _user(user_id: int, name: str) -> User:
    return User(id=user_id, is_bot=False, first_name=name, username="e2e")


def message_update(chat_id: int, user_id: int, text: str, name: str = "E2E") -> Update:
    return Update(
        update_id=next(_update_ids),
        message=Message(
            message_id=next(_message_ids),
            date=datetime.now(),
            chat=Chat(id=chat_id, type="private"),
            from_user=_user(user_id, name),
            text=text,
        ),
    )


def callback_update(chat_id: int, user_id: int, data: str, name: str = "E2E") -> Update:
    return Update(
        update_id=next(_update_ids),
        callback_query=CallbackQuery(
            id=str(next(_update_ids)),
            from_user=_user(user_id, name),
            chat_instance="e2e",
            data=data,
            message=Message(
                message_id=next(_message_ids),
                date=datetime.now(),
                chat=Chat(id=chat_id, type="private"),
                from_user=User(id=1, is_bot=True, first_name="Bot"),
                text="…",
            ),
        ),
    )


async def feed(runtime: Runtime, update: Update) -> list[str]:
    runtime.sent.clear()
    await runtime.dispatcher.feed_update(runtime.bot, update)
    return list(runtime.sent)


# -- scenario ---------------------------------------------------------------


@dataclass
class Step:
    name: str
    action: Callable[[Runtime, dict[str, Any]], Any]
    expect: Callable[[list[str], dict[str, Any]], str | None]
    """Return None when the replies are acceptable, or a reason when not."""


def _expression_of(text: str) -> str | None:
    match = re.search(r"<code>(.+?)</code>", text)
    return match.group(1) if match else None


def _find_expression(replies: list[str]) -> str | None:
    for reply in reversed(replies):
        expression = _expression_of(reply)
        if expression:
            return expression
    return None


def _needs_problem(replies: list[str], state: dict[str, Any]) -> str | None:
    expression = _find_expression(replies)
    if not expression:
        return "no problem was issued"
    try:
        state["answer"] = evaluate_display(expression)
    except Exception as exc:  # noqa: BLE001
        return f"issued an expression that does not evaluate: {expression} ({exc})"
    state["expression"] = expression
    return None


def build_scenario(chat_id: int, user_id: int, profile: str) -> list[Step]:
    """A full session, start to finish, with every reply checked."""
    return [
        Step(
            "reset any previous session",
            lambda runtime, state: feed(runtime, message_update(chat_id, user_id, "/stop")),
            lambda replies, state: None if replies else "no reply to /stop",
        ),
        Step(
            "/start greets",
            lambda runtime, state: feed(runtime, message_update(chat_id, user_id, "/start")),
            lambda replies, state: (
                None if any(reply.strip() for reply in replies) else "no reply to /start"
            ),
        ),
        Step(
            "/level offers the grade choice",
            lambda runtime, state: feed(runtime, message_update(chat_id, user_id, "/level")),
            lambda replies, state: (
                None if any("Выбери" in reply for reply in replies) else "no grade choice offered"
            ),
        ),
        Step(
            "choosing a grade issues a problem",
            lambda runtime, state: feed(
                runtime, callback_update(chat_id, user_id, f"profile:{profile}")
            ),
            _needs_problem,
        ),
        Step(
            "a correct answer is accepted and a new problem follows",
            lambda runtime, state: feed(
                runtime, message_update(chat_id, user_id, str(state["answer"]))
            ),
            _needs_problem,
        ),
        Step(
            "a wrong answer keeps the same problem",
            lambda runtime, state: feed(
                runtime, message_update(chat_id, user_id, str(state["answer"] + 1))
            ),
            lambda replies, state: (
                None
                if any(state["expression"] in reply for reply in replies)
                else "the problem was not restated after a wrong answer"
            ),
        ),
        Step(
            "a second wrong answer still keeps it",
            lambda runtime, state: feed(
                runtime, message_update(chat_id, user_id, str(state["answer"] + 2))
            ),
            lambda replies, state: (
                None
                if any(state["expression"] in reply for reply in replies)
                else "the problem was not restated after the second wrong answer"
            ),
        ),
        Step(
            "the third wrong answer reveals the answer and moves on",
            lambda runtime, state: feed(
                runtime, message_update(chat_id, user_id, str(state["answer"] + 3))
            ),
            lambda replies, state: (
                None
                if any(str(state["answer"]) in reply for reply in replies)
                and _find_expression(replies)
                else "the correct answer was not revealed, or no new problem followed"
            ),
        ),
        Step(
            "non-numeric input is corrected, not judged",
            lambda runtime, state: feed(
                runtime, message_update(chat_id, user_id, "не знаю")
            ),
            lambda replies, state: (
                None
                if any("<code>" in reply for reply in replies)
                else "the problem was not restated after unparseable input"
            ),
        ),
        Step(
            "/stop closes the session",
            lambda runtime, state: feed(runtime, message_update(chat_id, user_id, "/stop")),
            lambda replies, state: None if replies else "no reply to /stop",
        ),
    ]


def admin_steps(chat_id: int, admin_id: int) -> list[Step]:
    return [
        Step(
            "/stats reports usage",
            lambda runtime, state: feed(
                runtime, message_update(chat_id, admin_id, "/stats", "Admin")
            ),
            lambda replies, state: (
                None if any("Статистика" in reply for reply in replies) else "no statistics"
            ),
        ),
        Step(
            "/health reports technical state",
            lambda runtime, state: feed(
                runtime, message_update(chat_id, admin_id, "/health", "Admin")
            ),
            lambda replies, state: (
                None if any("аптайм" in reply for reply in replies) else "no health readout"
            ),
        ),
    ]


async def run_scenario(
    chat_id: int, user_id: int, admin_id: int | None, profile: str, pace: float = 1.0
) -> int:
    """Play the scenario.

    `pace` spaces the steps out. The bot throttles a user who sends faster than
    a human plausibly types, and the harness must not trip its own defences —
    so the smoke check runs against the *production* rate limit rather than
    quietly relaxing it.
    """
    runtime = await build_runtime()
    state: dict[str, Any] = {}
    failures = 0

    try:
        me = await runtime.bot.get_me()
        print(f"connected as @{me.username} (id={me.id})")

        steps = build_scenario(chat_id, user_id, profile)
        if admin_id is not None:
            steps += admin_steps(chat_id, admin_id)

        for index, step in enumerate(steps, start=1):
            if index > 1 and pace:
                await asyncio.sleep(pace)
            replies = await step.action(runtime, state)
            problem = step.expect(replies, state)
            if problem is None:
                print(f"  {index:2}. ✅ {step.name}")
            else:
                failures += 1
                print(f"  {index:2}. ❌ {step.name}: {problem}")
                for reply in replies:
                    print(f"        got: {reply[:160]!r}")
                # Later steps depend on this one's state; stop at the first break.
                break
    finally:
        await runtime.close()

    if failures:
        print(f"\nFAILED after {failures} problem(s)")
        return 1
    print("\nOK — every step passed")
    return 0


async def run_send(chat_id: int, user_id: int, text: str) -> int:
    runtime = await build_runtime()
    try:
        replies = await feed(runtime, message_update(chat_id, user_id, text))
        for reply in replies:
            print(reply)
        return 0 if replies else 1
    finally:
        await runtime.close()


async def run_fetch_chat_id() -> int:
    """Print the chat ids of whoever has messaged the bot recently.

    Telegram will not let a bot write to a chat it has never received a message
    from, so this is the one step that needs a human — once, ever.
    """
    settings = Settings.from_env()
    bot = build_bot(settings)
    try:
        updates = await bot.get_updates(limit=100, timeout=5)
        if not updates:
            print("No pending updates. Send the bot a message, then run this again.")
            return 1
        seen: set[tuple[int, int]] = set()
        for update in updates:
            message = update.message or update.edited_message
            if message and message.from_user:
                key = (message.chat.id, message.from_user.id)
                if key not in seen:
                    seen.add(key)
                    print(
                        f"chat_id={message.chat.id} user_id={message.from_user.id} "
                        f"name={message.from_user.full_name!r}"
                    )
        return 0
    finally:
        await bot.session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)

    subparsers.add_parser("fetch-chat-id", help="List chats that have messaged the bot")

    send = subparsers.add_parser("send", help="Send one message through the real pipeline")
    send.add_argument("text")
    send.add_argument("--chat-id", type=int, required=True)
    send.add_argument("--user-id", type=int)

    scenario = subparsers.add_parser("scenario", help="Play a whole session and check every reply")
    scenario.add_argument("--chat-id", type=int, required=True)
    scenario.add_argument("--user-id", type=int)
    scenario.add_argument("--admin-id", type=int, help="Also exercise the admin commands")
    scenario.add_argument("--profile", default="grade4")
    scenario.add_argument(
        "--pace",
        type=float,
        default=1.0,
        help="Seconds between steps; must stay under the bot's own rate limit",
    )

    args = parser.parse_args()

    if args.action == "fetch-chat-id":
        sys.exit(asyncio.run(run_fetch_chat_id()))
    if args.action == "send":
        sys.exit(asyncio.run(run_send(args.chat_id, args.user_id or args.chat_id, args.text)))
    if args.action == "scenario":
        sys.exit(
            asyncio.run(
                run_scenario(
                    args.chat_id,
                    args.user_id or args.chat_id,
                    args.admin_id,
                    args.profile,
                    args.pace,
                )
            )
        )


if __name__ == "__main__":
    main()

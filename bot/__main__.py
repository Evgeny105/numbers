"""Entry point: wire everything together and poll Telegram."""

from __future__ import annotations

import asyncio
import logging
import sys
import time

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from bot.config import ConfigError, Settings
from bot.handlers import admin as admin_handlers
from bot.handlers import fallback as fallback_handlers
from bot.handlers import quiz as quiz_handlers
from bot.handlers import start as start_handlers
from bot.logging_setup import setup_logging
from bot.middlewares.audit import AuditMiddleware
from bot.middlewares.ban import BanMiddleware
from bot.middlewares.throttle import ThrottleMiddleware
from bot.services.llm import LLMClient, build_providers
from bot.services.openrouter import OpenRouterService
from bot.services.phrase_service import PhraseService
from bot.storage.db import Database
from bot.storage.redis_storage import build_storage

_LOGGER = logging.getLogger(__name__)


def build_bot(settings: Settings) -> Bot:
    """A bot whose Telegram traffic goes through the proxy when one is set."""
    session = AiohttpSession(proxy=settings.http_proxy_url) if settings.http_proxy_url else None
    return Bot(
        settings.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def build_dispatcher(
    settings: Settings,
    db: Database,
    phrases: PhraseService,
    openrouter: OpenRouterService,
    storage: object | None = None,
    started_at: float | None = None,
) -> Dispatcher:
    """Assemble the dispatcher: middlewares, routers, and shared services.

    Kept separate from `main` so the tests and the end-to-end harness build the
    exact same pipeline the production bot runs.
    """
    dispatcher = Dispatcher(storage=storage) if storage is not None else Dispatcher()

    ban_middleware = BanMiddleware(db)
    throttle_middleware = ThrottleMiddleware(
        db, settings.throttle_messages, settings.throttle_window_seconds
    )
    # Order matters: bans cost nothing to check and stop the most traffic, then
    # throttling, then the audit that writes to the database.
    for observer in (dispatcher.message, dispatcher.callback_query):
        observer.outer_middleware(ban_middleware)
        observer.outer_middleware(throttle_middleware)
        observer.outer_middleware(AuditMiddleware(db, settings.session_idle_timeout_seconds))

    dispatcher["db"] = db
    dispatcher["phrases"] = phrases
    dispatcher["openrouter"] = openrouter
    dispatcher["settings"] = settings
    dispatcher["ban_middleware"] = ban_middleware
    dispatcher["throttle_middleware"] = throttle_middleware
    dispatcher["max_input_length"] = settings.max_input_length
    dispatcher["started_at"] = started_at if started_at is not None else time.time()

    # Admin first so its commands are not swallowed by the quiz state handler,
    # then the ordinary flow, then the catch-all.
    dispatcher.include_router(admin_handlers.build_router(settings.admin_ids))
    dispatcher.include_router(start_handlers.build_router())
    dispatcher.include_router(quiz_handlers.build_router())
    dispatcher.include_router(fallback_handlers.build_router())
    return dispatcher


async def run() -> None:
    settings = Settings.from_env()
    setup_logging(settings.log_level, settings.db_path)
    _LOGGER.info("starting numbers math bot")
    _LOGGER.info("%s", settings.describe())

    started_at = time.time()
    db = await Database(settings.db_path).connect()
    storage = await build_storage(settings.redis_url)
    llm = LLMClient(build_providers(settings))
    _LOGGER.info(
        "llm providers: %s",
        ", ".join(provider.name for provider in build_providers(settings)) or "<none>",
    )

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
    dispatcher = build_dispatcher(settings, db, phrases, openrouter, storage, started_at)

    try:
        me = await bot.get_me()
        _LOGGER.info("connected to Telegram as @%s (id=%s)", me.username, me.id)
        await phrases.start()
        await dispatcher.start_polling(bot)
    finally:
        _LOGGER.info("shutting down")
        await phrases.stop()
        await llm.close()
        await db.close()
        await bot.session.close()


def main() -> None:
    try:
        asyncio.run(run())
    except ConfigError as exc:
        # Say why, in one line, rather than restart-looping in silence.
        logging.basicConfig(level=logging.ERROR)
        logging.getLogger(__name__).error("configuration error: %s", exc)
        sys.exit(2)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

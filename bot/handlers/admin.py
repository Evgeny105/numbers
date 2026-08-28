"""Administrator commands.

Gated on `ADMIN_IDS`. A non-administrator sending one of these gets nothing back
from this router and falls through to the ordinary fallback reply, so the
existence of the commands is not disclosed.
"""

from __future__ import annotations

import html
import logging
import time
from datetime import datetime

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.middlewares.ban import BanMiddleware
from bot.services.openrouter import OpenRouterService, format_report
from bot.services.phrase_service import PhraseService
from bot.storage import phrases as phrase_store
from bot.storage import queries
from bot.storage.db import Database

_LOGGER = logging.getLogger(__name__)

def admin_filter(admin_ids: frozenset[int]):
    """A filter passing only configured administrator ids.

    Deliberately a coroutine *function* rather than an object with an async
    `__call__`: aiogram detects the former and awaits it, but treats the latter
    as a plain callable and takes the returned coroutine — which is always
    truthy — as a pass. That mistake let any user run every admin command.
    """

    async def check(message: Message) -> bool:
        return message.from_user is not None and message.from_user.id in admin_ids

    return check


def build_router(admin_ids: frozenset[int]) -> Router:
    """A router whose every handler is gated on the administrator list."""
    router = Router(name="admin")
    router.message.filter(admin_filter(admin_ids))
    router.message.register(stats_handler, Command("stats"))
    router.message.register(users_handler, Command("users"))
    router.message.register(user_handler, Command("user"))
    router.message.register(ban_handler, Command("ban"))
    router.message.register(unban_handler, Command("unban"))
    router.message.register(phrases_handler, Command("phrases"))
    router.message.register(balance_handler, Command("balance"))
    router.message.register(health_handler, Command("health"))
    return router


def _when(ts: float | None) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%d.%m %H:%M")


def _pct(value: float) -> str:
    return f"{value * 100:.0f}%"


async def stats_handler(message: Message, db: Database) -> None:
    today = await queries.summary(db, days=1)
    week = await queries.summary(db, days=7)
    lines = ["<b>Статистика</b>"]
    for label, data in (("За сутки", today), ("За неделю", week)):
        lines.append(
            f"\n<b>{label}</b>\n"
            f"пользователей: {data['users']}\n"
            f"ответов: {data['attempts']} (верных {data['correct']}, {_pct(data['success_rate'])})\n"
            f"примеров: {data['problems']}"
        )
    await message.answer("\n".join(lines))
    _LOGGER.info("admin %s requested stats", message.from_user.id if message.from_user else "?")


async def users_handler(message: Message, db: Database) -> None:
    users = await queries.user_list(db)
    if not users:
        await message.answer("Пока никого нет.")
        return

    lines = [f"<b>Пользователи ({len(users)})</b>"]
    for user in users[:30]:
        name = html.escape(str(user["full_name"] or user["tg_username"] or user["user_id"]))
        flag = " 🚫" if user["banned"] else ""
        lines.append(
            f"\n<b>{name}</b>{flag} <code>{user['user_id']}</code>\n"
            f"уровень {user['grade_profile'] or '—'}, сложность {user['difficulty']}, "
            f"баллов {user['score']}\n"
            f"ответов {user['attempts']} ({_pct(user['success_rate'])}), "
            f"был {_when(user['last_seen'])}"
        )
    if len(users) > 30:
        lines.append(f"\n…и ещё {len(users) - 30}")
    await message.answer("\n".join(lines))


async def user_handler(message: Message, command: CommandObject, db: Database) -> None:
    if not command.args or not command.args.strip().lstrip("-").isdigit():
        await message.answer("Нужен id: <code>/user 123456</code>")
        return

    user_id = int(command.args.strip())
    detail = await queries.user_detail(db, user_id)
    if detail is None:
        await message.answer("Такого пользователя нет.")
        return

    name = html.escape(str(detail["full_name"] or detail["tg_username"] or user_id))
    lines = [
        f"<b>{name}</b> <code>{user_id}</code>",
        f"уровень: {detail['grade_profile'] or '—'}, сложность {detail['difficulty']}, "
        f"баллов {detail['score']}",
        f"ответов: {detail['attempts']} (верных {detail['correct']}, "
        f"{_pct(detail['success_rate'])})",
        f"сессий: {detail['sessions']}",
        f"первый раз: {_when(detail['first_seen'])}, последний: {_when(detail['last_seen'])}",
    ]
    if detail["banned"]:
        lines.append(f"🚫 забанен: {detail['ban_reason'] or 'без причины'}")

    attempts = await queries.recent_attempts(db, user_id, limit=10)
    if attempts:
        lines.append("\n<b>Последние ответы</b>")
        for attempt in attempts:
            mark = "✅" if attempt["is_correct"] else "❌"
            lines.append(
                f"{mark} <code>{html.escape(str(attempt['expression']))}</code> = "
                f"{attempt['correct_answer']}, ответил {html.escape(str(attempt['given_answer']))} "
                f"(попытка {attempt['attempt_no']}, {_when(attempt['ts'])})"
            )
    await message.answer("\n".join(lines))


async def ban_handler(
    message: Message, command: CommandObject, db: Database, ban_middleware: BanMiddleware
) -> None:
    parts = (command.args or "").split(maxsplit=1)
    if not parts or not parts[0].lstrip("-").isdigit():
        await message.answer("Нужен id: <code>/ban 123456 причина</code>")
        return

    user_id = int(parts[0])
    reason = parts[1] if len(parts) > 1 else None
    admin_id = message.from_user.id if message.from_user else None
    await db.set_ban(user_id, True, by_admin=admin_id, reason=reason)
    ban_middleware.invalidate()
    _LOGGER.warning("admin %s banned user %s (%s)", admin_id, user_id, reason or "no reason")
    await message.answer(f"Пользователь <code>{user_id}</code> забанен.")


async def unban_handler(
    message: Message, command: CommandObject, db: Database, ban_middleware: BanMiddleware
) -> None:
    if not command.args or not command.args.strip().lstrip("-").isdigit():
        await message.answer("Нужен id: <code>/unban 123456</code>")
        return

    user_id = int(command.args.strip())
    admin_id = message.from_user.id if message.from_user else None
    await db.set_ban(user_id, False, by_admin=admin_id)
    ban_middleware.invalidate()
    _LOGGER.warning("admin %s unbanned user %s", admin_id, user_id)
    await message.answer(f"Пользователь <code>{user_id}</code> разбанен.")


async def phrases_handler(message: Message, db: Database, phrases: PhraseService) -> None:
    overview = await phrase_store.pool_overview(db)
    if not overview:
        await message.answer("Пул реплик пуст — идёт первое наполнение.")
        return

    lines = ["<b>Пул реплик</b>"]
    for row in overview:
        lines.append(
            f"{row['category']}: {row['usable']} готовых"
            + (f", {row['disabled']} отключено" if row["disabled"] else "")
        )
    await message.answer("\n".join(lines))


async def balance_handler(message: Message, openrouter: OpenRouterService) -> None:
    report = await openrouter.get()
    await message.answer(format_report(report))


async def health_handler(message: Message, db: Database, started_at: float) -> None:
    """A quick technical readout, so debugging does not always need ssh."""
    uptime = int(time.time() - started_at)
    users = int(await db.fetch_value("SELECT COUNT(*) FROM users", default=0))
    attempts = int(await db.fetch_value("SELECT COUNT(*) FROM attempts", default=0))
    events = int(await db.fetch_value("SELECT COUNT(*) FROM events", default=0))
    pool = sum(int(row["usable"] or 0) for row in await phrase_store.pool_overview(db))
    await message.answer(
        "<b>Состояние</b>\n"
        f"аптайм: {uptime // 3600} ч {uptime % 3600 // 60} мин\n"
        f"база: {db.path}\n"
        f"пользователей: {users}, ответов: {attempts}, событий: {events}\n"
        f"реплик в пуле: {pool}"
    )

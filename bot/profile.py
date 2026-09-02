"""The bot configures its own Telegram presence on startup.

The command menu, the display name and the two descriptions are ordinary Bot
API methods, so the bot sets them itself. BotFather is no longer a step anyone
has to remember after adding a handler, and the menu cannot drift away from the
commands that actually exist — a unit test cross-checks the two.

Every value is read back with the matching `getMy*` before being written. A
container restarts on every deploy, and spending half a dozen pointless API
calls each time is both noise in the log and needless pressure on Telegram's
rate limits. The read also catches a value someone changed by hand in
BotFather, and restores it.

Administrators get a longer menu through `BotCommandScopeChat`. The bot already
refuses admin commands from everyone else; without this the *menu* still
advertised them to whoever BotFather was last told about. Comparison is done
per administrator: two chats' command lists cannot be diffed in bulk.

Telegram has no API for the avatar or the accent colour. Those stay a one-off
`/setuserpic` in BotFather.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol

from aiogram.enums import MenuButtonType
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    MenuButtonCommands,
)

_LOGGER = logging.getLogger(__name__)

_COMMAND_RE = re.compile(r"^[a-z0-9_]+$")

MAX_NAME = 64
MAX_DESCRIPTION = 512
MAX_SHORT_DESCRIPTION = 120

#: What everyone sees. Order is the order Telegram shows them in.
USER_COMMANDS: tuple[tuple[str, str], ...] = (
    ("start", "Начать или продолжить тренировку"),
    ("level", "Выбрать класс — какие примеры давать"),
    ("stop", "Закончить занятие"),
    ("help", "Что я умею"),
)

#: What administrators see in addition.
ADMIN_COMMANDS: tuple[tuple[str, str], ...] = (
    ("stats", "Сводка за сутки и за неделю"),
    ("users", "Кто пользуется ботом"),
    ("user", "Карточка пользователя по id"),
    ("ban", "Забанить пользователя"),
    ("unban", "Разбанить пользователя"),
    ("phrases", "Состояние пула реплик"),
    ("balance", "Баланс OpenRouter"),
    ("health", "Техническое состояние"),
)

#: Shown on the empty chat screen, before the child has pressed /start.
DESCRIPTION = (
    "Я тренирую устный счёт. Даю примеры по силам, три попытки на каждый, "
    "считаю баллы и подбираю сложность под тебя.\n\n"
    "Нажми «Начать», выбери класс — и поехали!"
)

#: Shown in the profile and in link previews.
SHORT_DESCRIPTION = "Тренажёр устного счёта: примеры по силам, три попытки, баллы и уровни."


@dataclass(frozen=True)
class BotProfile:
    """The presence the bot should have.

    Attributes:
        description: Empty-chat text, at most 512 characters.
        short_description: Profile text, at most 120 characters.
        commands: Commands everyone sees, as (name, description) pairs.
        admin_commands: Commands administrators additionally see.
        admin_ids: Who gets the longer menu.
        name: Display name, at most 64 characters. `None` leaves whatever the
            bot is already called alone — renaming somebody's bot is not a side
            effect a deploy should have unless it was asked for.
    """

    description: str
    short_description: str
    commands: tuple[tuple[str, str], ...]
    admin_commands: tuple[tuple[str, str], ...] = ()
    admin_ids: tuple[int, ...] = ()
    name: str | None = None

    def admin_menu(self) -> tuple[tuple[str, str], ...]:
        """The full menu an administrator sees: theirs on top of everyone's."""
        return self.commands + self.admin_commands


class _BotLike(Protocol):
    """The slice of the Bot API this module uses.

    Keyword-only, because that is how `apply_profile` calls them, and the real
    `Bot` puts these parameters at different positions (`set_chat_menu_button`
    takes `chat_id` first, not `menu_button`).
    """

    async def get_my_name(self) -> Any: ...
    async def get_my_description(self) -> Any: ...
    async def get_my_short_description(self) -> Any: ...
    async def get_my_commands(self, *, scope: Any = None) -> Any: ...
    async def set_my_name(self, *, name: str) -> Any: ...
    async def set_my_description(self, *, description: str) -> Any: ...
    async def set_my_short_description(self, *, short_description: str) -> Any: ...
    async def set_my_commands(self, *, commands: list[BotCommand], scope: Any = None) -> Any: ...
    async def get_chat_menu_button(self) -> Any: ...
    async def set_chat_menu_button(self, *, menu_button: Any = None) -> Any: ...


def build_profile(admin_ids: Iterable[int] = (), name: str | None = None) -> BotProfile:
    """The profile this bot should have, validated before any network call.

    Who counts as an administrator comes from configuration (`ADMIN_IDS`), not
    from this module: the same code runs against a test bot and a deployed one
    with different administrators.
    """
    profile = BotProfile(
        description=DESCRIPTION,
        short_description=SHORT_DESCRIPTION,
        commands=USER_COMMANDS,
        admin_commands=ADMIN_COMMANDS,
        admin_ids=tuple(sorted(admin_ids)),
        name=name.strip() if name and name.strip() else None,
    )
    validate(profile)
    return profile


def validate(profile: BotProfile) -> None:
    """Check Telegram's limits locally, so a bad value fails before it is sent."""
    if profile.name is not None and len(profile.name) > MAX_NAME:
        raise ValueError(f"name is longer than {MAX_NAME} characters")
    if len(profile.description) > MAX_DESCRIPTION:
        raise ValueError(f"description is longer than {MAX_DESCRIPTION} characters")
    if len(profile.short_description) > MAX_SHORT_DESCRIPTION:
        raise ValueError(
            f"short_description is longer than {MAX_SHORT_DESCRIPTION} characters"
        )

    menu = profile.admin_menu()
    if len(menu) > 100:
        raise ValueError("more than 100 commands in a single menu")

    seen: set[str] = set()
    for command, description in menu:
        if not 1 <= len(command) <= 32:
            raise ValueError(f"command {command!r}: length outside 1..32")
        if not _COMMAND_RE.match(command):
            raise ValueError(f"command {command!r}: only lowercase [a-z0-9_] is allowed")
        if not 1 <= len(description) <= 256:
            raise ValueError(f"description of {command!r}: length outside 1..256")
        if command in seen:
            raise ValueError(f"command {command!r} is listed twice")
        seen.add(command)


def _to_commands(pairs: tuple[tuple[str, str], ...]) -> list[BotCommand]:
    return [BotCommand(command=name, description=text) for name, text in pairs]


async def _current_commands(bot: _BotLike, scope: Any = None) -> tuple[tuple[str, str], ...]:
    current = await bot.get_my_commands(scope=scope)
    return tuple((item.command, item.description) for item in current)


async def sync_admin_menu(bot: _BotLike, admin_id: int, profile: BotProfile) -> bool:
    """Give one administrator the longer menu. Returns True if it changed.

    Telegram refuses a chat scope for a chat the bot has never received a
    message from, which is exactly the state a fresh administrator is in. That
    is not an error worth failing a startup over, so it is logged and reported
    as "not applied" — the caller can try again later, once the administrator
    has said something.
    """
    scope = BotCommandScopeChat(chat_id=admin_id)
    wanted = profile.admin_menu()
    try:
        if await _current_commands(bot, scope) == wanted:
            return False
        await bot.set_my_commands(commands=_to_commands(wanted), scope=scope)
    except TelegramBadRequest as exc:
        _LOGGER.info("admin menu for %s not applied yet: %s", admin_id, exc)
        return False
    _LOGGER.info("admin menu applied for %s", admin_id)
    return True


async def apply_profile(bot: _BotLike, profile: BotProfile) -> list[str]:
    """Bring the bot's presence to the wanted state.

    Returns the names of the parts that changed; an empty list means everything
    already matched, which is the normal case on a restart.
    """
    changed: list[str] = []

    if profile.name is not None:
        if (await bot.get_my_name()).name != profile.name:
            await bot.set_my_name(name=profile.name)
            changed.append("name")

    if (await bot.get_my_description()).description != profile.description:
        await bot.set_my_description(description=profile.description)
        changed.append("description")

    if (await bot.get_my_short_description()).short_description != profile.short_description:
        await bot.set_my_short_description(short_description=profile.short_description)
        changed.append("short_description")

    if await _current_commands(bot) != profile.commands:
        await bot.set_my_commands(
            commands=_to_commands(profile.commands), scope=BotCommandScopeDefault()
        )
        changed.append("commands")

    for admin_id in profile.admin_ids:
        if await sync_admin_menu(bot, admin_id, profile):
            changed.append(f"commands:{admin_id}")

    # Checked on its own rather than alongside the commands: if the button was
    # switched to something else by hand, reading its state is what notices.
    if (await bot.get_chat_menu_button()).type != MenuButtonType.COMMANDS:
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        changed.append("menu_button")

    _LOGGER.info("bot profile: changed %s", ", ".join(changed) if changed else "nothing")
    return changed

"""The bot's own presence: set only on a difference, and never out of step.

The point of these tests is the two failure modes that matter. One: a restart
must not spend API calls re-writing values that already match. Two: the menu
must not drift away from the commands the routers actually register — that
drift is silent, and is exactly what happened between the 2025 version and
this one.
"""

from __future__ import annotations

import pytest
from aiogram.enums import MenuButtonType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    BotDescription,
    BotName,
    BotShortDescription,
    MenuButtonCommands,
    MenuButtonDefault,
)

from bot import profile as profile_module
from bot.handlers import admin as admin_handlers
from bot.handlers import fallback as fallback_handlers
from bot.handlers import quiz as quiz_handlers
from bot.handlers import start as start_handlers
from bot.profile import (
    ADMIN_COMMANDS,
    USER_COMMANDS,
    BotProfile,
    apply_profile,
    build_profile,
    sync_admin_menu,
    validate,
)

ADMIN_ID = 4242


class FakeBot:
    """Records what was written, and answers the getters from that state."""

    def __init__(
        self,
        name: str = "",
        description: str = "",
        short_description: str = "",
        commands: tuple[tuple[str, str], ...] = (),
        admin_commands: dict[int, tuple[tuple[str, str], ...]] | None = None,
        menu_button: object | None = None,
        chat_scope_fails: bool = False,
    ) -> None:
        self.name = name
        self.description = description
        self.short_description = short_description
        self.commands = commands
        self.admin_commands = dict(admin_commands or {})
        self.menu_button = menu_button or MenuButtonDefault()
        self.chat_scope_fails = chat_scope_fails
        self.calls: list[str] = []

    # -- getters
    async def get_my_name(self, **_: object):
        return BotName(name=self.name)

    async def get_my_description(self, **_: object):
        return BotDescription(description=self.description)

    async def get_my_short_description(self, **_: object):
        return BotShortDescription(short_description=self.short_description)

    async def get_my_commands(self, scope: object = None, **_: object):
        if isinstance(scope, BotCommandScopeChat):
            if self.chat_scope_fails:
                raise TelegramBadRequest(method=None, message="Bad Request: chat not found")
            pairs = self.admin_commands.get(scope.chat_id, ())
        else:
            pairs = self.commands
        return [BotCommand(command=name, description=text) for name, text in pairs]

    async def get_chat_menu_button(self, **_: object):
        return self.menu_button

    # -- setters
    async def set_my_name(self, name: str, **_: object) -> None:
        self.calls.append("set_name")
        self.name = name

    async def set_my_description(self, description: str, **_: object) -> None:
        self.calls.append("set_description")
        self.description = description

    async def set_my_short_description(self, short_description: str, **_: object) -> None:
        self.calls.append("set_short_description")
        self.short_description = short_description

    async def set_my_commands(
        self, commands: list[BotCommand], scope: object = None, **_: object
    ) -> None:
        pairs = tuple((c.command, c.description) for c in commands)
        if isinstance(scope, BotCommandScopeChat):
            if self.chat_scope_fails:
                raise TelegramBadRequest(method=None, message="Bad Request: chat not found")
            self.calls.append(f"set_commands:{scope.chat_id}")
            self.admin_commands[scope.chat_id] = pairs
        else:
            self.calls.append("set_commands")
            self.commands = pairs

    async def set_chat_menu_button(self, menu_button: object = None, **_: object) -> None:
        self.calls.append("set_menu_button")
        self.menu_button = menu_button


def in_sync_bot(profile: BotProfile) -> FakeBot:
    """A bot already in the wanted state."""
    return FakeBot(
        name=profile.name or "",
        description=profile.description,
        short_description=profile.short_description,
        commands=profile.commands,
        admin_commands={admin: profile.admin_menu() for admin in profile.admin_ids},
        menu_button=MenuButtonCommands(),
    )


class TestApply:
    async def test_a_fresh_bot_gets_everything(self) -> None:
        profile = build_profile([ADMIN_ID], name="Считалка")
        bot = FakeBot()

        changed = await apply_profile(bot, profile)

        assert changed == [
            "name",
            "description",
            "short_description",
            "commands",
            f"commands:{ADMIN_ID}",
            "menu_button",
        ]
        assert bot.commands == USER_COMMANDS
        assert bot.admin_commands[ADMIN_ID] == USER_COMMANDS + ADMIN_COMMANDS

    async def test_a_restart_writes_nothing(self) -> None:
        """The whole point of reading before writing."""
        profile = build_profile([ADMIN_ID], name="Считалка")
        bot = in_sync_bot(profile)

        assert await apply_profile(bot, profile) == []
        assert bot.calls == []

    async def test_only_the_part_that_differs_is_written(self) -> None:
        profile = build_profile([ADMIN_ID])
        bot = in_sync_bot(profile)
        bot.short_description = "что-то старое"

        assert await apply_profile(bot, profile) == ["short_description"]
        assert bot.calls == ["set_short_description"]

    async def test_an_unset_name_leaves_the_bot_alone(self) -> None:
        """A deploy must not rename somebody's bot as a side effect."""
        profile = build_profile([ADMIN_ID])
        bot = in_sync_bot(profile)
        bot.name = "math_ev"

        assert await apply_profile(bot, profile) == []
        assert bot.name == "math_ev"

    async def test_a_hand_switched_menu_button_is_restored(self) -> None:
        """Read the button's own state; do not infer it from the commands."""
        profile = build_profile([ADMIN_ID])
        bot = in_sync_bot(profile)
        bot.menu_button = MenuButtonDefault()

        assert await apply_profile(bot, profile) == ["menu_button"]
        assert bot.menu_button.type == MenuButtonType.COMMANDS


class TestAdminMenu:
    async def test_administrators_see_more_than_users(self) -> None:
        profile = build_profile([ADMIN_ID])
        bot = FakeBot()
        await apply_profile(bot, profile)

        user_menu = {name for name, _ in bot.commands}
        admin_menu = {name for name, _ in bot.admin_commands[ADMIN_ID]}

        assert user_menu == {name for name, _ in USER_COMMANDS}
        assert admin_menu == user_menu | {name for name, _ in ADMIN_COMMANDS}
        # No admin command may leak into the menu everyone sees.
        assert not user_menu & {name for name, _ in ADMIN_COMMANDS}

    async def test_each_administrator_is_compared_separately(self) -> None:
        """Two chats' menus cannot be diffed in bulk."""
        profile = build_profile([ADMIN_ID, ADMIN_ID + 1])
        bot = in_sync_bot(profile)
        bot.admin_commands[ADMIN_ID + 1] = ()

        changed = await apply_profile(bot, profile)

        assert changed == [f"commands:{ADMIN_ID + 1}"]
        assert bot.calls == [f"set_commands:{ADMIN_ID + 1}"]

    async def test_an_unreachable_chat_is_not_an_error(self) -> None:
        """Telegram refuses a chat scope until the admin has written once."""
        profile = build_profile([ADMIN_ID])
        bot = FakeBot(chat_scope_fails=True)

        changed = await apply_profile(bot, profile)

        assert f"commands:{ADMIN_ID}" not in changed
        assert "commands" in changed  # everything else still applied

    async def test_sync_admin_menu_reports_whether_it_changed(self) -> None:
        profile = build_profile([ADMIN_ID])
        bot = FakeBot()

        assert await sync_admin_menu(bot, ADMIN_ID, profile) is True
        assert await sync_admin_menu(bot, ADMIN_ID, profile) is False


class TestValidation:
    def test_the_real_profile_is_valid(self) -> None:
        validate(build_profile([1], name="Считалка"))

    @pytest.mark.parametrize(
        "field,value",
        [
            ("name", "и" * 65),
            ("description", "и" * 513),
            ("short_description", "и" * 121),
        ],
    )
    def test_an_over_long_text_is_refused(self, field: str, value: str) -> None:
        profile = build_profile([1], name="ok")
        with pytest.raises(ValueError):
            validate(BotProfile(**{**profile.__dict__, field: value}))

    @pytest.mark.parametrize(
        "command",
        ["Start", "with-dash", "с_кириллицей", "", "a" * 33],
    )
    def test_an_invalid_command_name_is_refused(self, command: str) -> None:
        profile = build_profile([1])
        with pytest.raises(ValueError):
            validate(BotProfile(**{**profile.__dict__, "commands": ((command, "текст"),)}))

    def test_a_duplicate_command_is_refused(self) -> None:
        profile = build_profile([1])
        with pytest.raises(ValueError):
            validate(
                BotProfile(**{**profile.__dict__, "admin_commands": (("start", "дубль"),)})
            )

    def test_an_empty_command_description_is_refused(self) -> None:
        profile = build_profile([1])
        with pytest.raises(ValueError):
            validate(BotProfile(**{**profile.__dict__, "commands": (("start", ""),)}))


def registered_commands() -> dict[str, set[str]]:
    """Command names the routers actually register, by audience."""

    def names(router) -> set[str]:
        found: set[str] = set()
        for handler in router.message.handlers:
            for filter_ in handler.filters or ():
                callback = getattr(filter_, "callback", filter_)
                if isinstance(callback, (Command, CommandStart)):
                    found.update(str(name) for name in (callback.commands or ()))
        return found

    return {
        "user": names(start_handlers.build_router())
        | names(quiz_handlers.build_router())
        | names(fallback_handlers.build_router()),
        "admin": names(admin_handlers.build_router(frozenset({ADMIN_ID}))),
    }


class TestNoDrift:
    """The menu is a promise about the handlers. Keep them equal.

    Between the 2025 version and this one the bot gained four commands and the
    BotFather menu never heard about it. A test is the only thing that notices.
    """

    def test_every_user_command_is_in_the_user_menu(self) -> None:
        assert registered_commands()["user"] == {name for name, _ in USER_COMMANDS}

    def test_every_admin_command_is_in_the_admin_menu(self) -> None:
        assert registered_commands()["admin"] == {name for name, _ in ADMIN_COMMANDS}

    def test_the_menus_do_not_overlap(self) -> None:
        assert not {name for name, _ in USER_COMMANDS} & {name for name, _ in ADMIN_COMMANDS}

    def test_descriptions_are_russian_and_useful(self) -> None:
        for name, description in USER_COMMANDS + ADMIN_COMMANDS:
            assert len(description) >= 5, f"{name}: description is too terse to help"
            assert any("а" <= char.lower() <= "я" for char in description), (
                f"{name}: description is not in Russian"
            )


class TestModuleShape:
    def test_limits_match_the_documented_api(self) -> None:
        assert (
            profile_module.MAX_NAME,
            profile_module.MAX_DESCRIPTION,
            profile_module.MAX_SHORT_DESCRIPTION,
        ) == (64, 512, 120)


class TestLazyAdminMenu:
    """An administrator who has never written to the bot still gets the menu.

    Telegram refuses the chat scope until that first message exists, so the
    first message is when to try again — not the next deploy.
    """

    async def test_the_first_admin_message_applies_the_menu(self, harness) -> None:
        from tests.conftest import TEST_ADMIN_ID

        await harness.send("/stats", user_id=TEST_ADMIN_ID)

        scopes = harness.session.command_scopes
        assert TEST_ADMIN_ID in scopes
        assert set(scopes[TEST_ADMIN_ID]) == {name for name, _ in USER_COMMANDS} | {
            name for name, _ in ADMIN_COMMANDS
        }

    async def test_it_is_not_repeated_on_every_message(self, harness) -> None:
        from tests.conftest import TEST_ADMIN_ID

        await harness.send("/stats", user_id=TEST_ADMIN_ID)
        await harness.send("/health", user_id=TEST_ADMIN_ID)

        assert harness.session.command_scopes == {}

    async def test_an_ordinary_user_never_triggers_it(self, harness) -> None:
        await harness.send("/start")
        assert harness.session.command_scopes == {}

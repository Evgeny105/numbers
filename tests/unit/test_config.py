"""Configuration read from the environment.

`from_env()` on both settings classes had no coverage at all, and a stray field
copied into `AdminWebSettings.from_env()` crash-looped the dashboard container
while every test still passed. These tests exercise the real entry point.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bot.config import AdminWebSettings, ConfigError, Settings, mask

MINIMAL_BOT_ENV = {"TOKEN_API_BOT": "123456:TESTTOKEN"}
MINIMAL_ADMIN_ENV = {"ADMIN_WEB_PASSWORD": "secret"}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Start from an empty environment, so a stray local value cannot mask a bug."""
    for name in (
        "TOKEN_API_BOT",
        "ADMIN_IDS",
        "E2E_BOT_TOKEN",
        "REDIS",
        "DB_PATH",
        "HTTP_PROXY_URL",
        "API_KEY_LLM",
        "LMSTUDIO_BASE_URL",
        "LMSTUDIO_MODEL",
        "OPENROUTER_BASE_URL",
        "OPENROUTER_MODEL",
        "BOT_DISPLAY_NAME",
        "ADMIN_WEB_USER",
        "ADMIN_WEB_PASSWORD",
        "ADMIN_WEB_BIND",
        "LOG_LEVEL",
        "THROTTLE_MESSAGES",
    ):
        monkeypatch.delenv(name, raising=False)


def set_env(monkeypatch, values: dict[str, str]) -> None:
    for name, value in values.items():
        monkeypatch.setenv(name, value)


class TestBotSettings:
    def test_a_minimal_environment_is_enough(self, monkeypatch) -> None:
        set_env(monkeypatch, MINIMAL_BOT_ENV)
        settings = Settings.from_env()

        assert settings.bot_token == "123456:TESTTOKEN"
        assert settings.admin_ids == frozenset()
        assert settings.bot_display_name == ""
        assert settings.db_path == Path("/data/numbers.sqlite3")

    def test_a_missing_token_names_the_variable(self, monkeypatch) -> None:
        with pytest.raises(ConfigError, match="TOKEN_API_BOT"):
            Settings.from_env()

    @pytest.mark.parametrize("raw", ["1,2, 3", "1;2;3", " 1 , 2 ,3 "])
    def test_admin_ids_tolerate_spacing_and_separators(self, monkeypatch, raw: str) -> None:
        set_env(monkeypatch, {**MINIMAL_BOT_ENV, "ADMIN_IDS": raw})
        assert Settings.from_env().admin_ids == frozenset({1, 2, 3})

    def test_a_non_numeric_admin_id_names_the_variable(self, monkeypatch) -> None:
        set_env(monkeypatch, {**MINIMAL_BOT_ENV, "ADMIN_IDS": "1,оператор"})
        with pytest.raises(ConfigError, match="ADMIN_IDS"):
            Settings.from_env()

    def test_a_non_numeric_integer_names_the_variable(self, monkeypatch) -> None:
        set_env(monkeypatch, {**MINIMAL_BOT_ENV, "THROTTLE_MESSAGES": "много"})
        with pytest.raises(ConfigError, match="THROTTLE_MESSAGES"):
            Settings.from_env()

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("redis:6379", "redis://redis:6379"),
            ("redis://elsewhere:6379/1", "redis://elsewhere:6379/1"),
            ("rediss://secure:6380", "rediss://secure:6380"),
        ],
    )
    def test_redis_accepts_a_bare_host_or_a_url(
        self, monkeypatch, raw: str, expected: str
    ) -> None:
        set_env(monkeypatch, {**MINIMAL_BOT_ENV, "REDIS": raw})
        assert Settings.from_env().redis_url == expected

    def test_lm_studio_is_absent_unless_configured(self, monkeypatch) -> None:
        """No host address is baked into the code."""
        set_env(monkeypatch, MINIMAL_BOT_ENV)
        assert Settings.from_env().lmstudio_base_url == ""

    def test_the_display_name_is_trimmed_and_optional(self, monkeypatch) -> None:
        set_env(monkeypatch, {**MINIMAL_BOT_ENV, "BOT_DISPLAY_NAME": "  Считалка  "})
        assert Settings.from_env().bot_display_name == "Считалка"

    def test_describe_masks_every_secret(self, monkeypatch) -> None:
        set_env(
            monkeypatch,
            {
                "TOKEN_API_BOT": "8190078967:AAsupersecrettokenvalue",
                "API_KEY_LLM": "sk-or-v1-supersecretkeyvalue0000",
            },
        )
        described = Settings.from_env().describe()

        assert "AAsupersecrettokenvalue" not in described
        assert "supersecretkeyvalue" not in described
        assert "8190078967" not in described


class TestAdminWebSettings:
    def test_a_minimal_environment_is_enough(self, monkeypatch) -> None:
        """The regression: this constructor was passed a field it does not have."""
        set_env(monkeypatch, MINIMAL_ADMIN_ENV)
        settings = AdminWebSettings.from_env()

        assert settings.admin_web_user == "admin"
        assert settings.admin_web_password == "secret"
        assert settings.db_path == Path("/data/numbers.sqlite3")

    def test_it_refuses_to_start_without_a_password(self, monkeypatch) -> None:
        with pytest.raises(ConfigError, match="ADMIN_WEB_PASSWORD"):
            AdminWebSettings.from_env()

    def test_it_takes_only_the_fields_it_declares(self, monkeypatch) -> None:
        """Nothing bot-specific may leak into the dashboard's settings."""
        set_env(monkeypatch, {**MINIMAL_ADMIN_ENV, "BOT_DISPLAY_NAME": "Считалка"})
        settings = AdminWebSettings.from_env()

        assert not hasattr(settings, "bot_display_name")
        assert not hasattr(settings, "bot_token")


class TestMask:
    @pytest.mark.parametrize(
        "secret,expected",
        [("", "<unset>"), ("short", "***"), ("0123456789abcdef", "012345...cdef")],
    )
    def test_masking(self, secret: str, expected: str) -> None:
        assert mask(secret) == expected

"""Application configuration, read from the environment and validated at startup.

Every setting comes from an environment variable. Nothing is read from a file at
runtime; `.env` is loaded by docker compose, or by the developer's shell.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(RuntimeError):
    """Raised when the environment is missing or malformed.

    The message always names the offending variable so a container that refuses
    to start says why in its first log line.
    """


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"Required environment variable {name!r} is not set")
    return value


def _optional(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"Environment variable {name!r} must be an integer, got {raw!r}") from exc


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"Environment variable {name!r} must be a number, got {raw!r}") from exc


def _ids(name: str) -> frozenset[int]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return frozenset()
    ids: set[int] = set()
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.add(int(chunk))
        except ValueError as exc:
            raise ConfigError(
                f"Environment variable {name!r} must be comma-separated numeric "
                f"Telegram user ids, got {chunk!r}"
            ) from exc
    return frozenset(ids)


def _redis_url(raw: str) -> str:
    """Accept either `host:port` or a full `redis://` URL, return a full URL."""
    if raw.startswith(("redis://", "rediss://", "unix://")):
        return raw
    return f"redis://{raw}"


def e2e_overrides() -> dict[str, str]:
    """Environment overrides the end-to-end harness applies to itself.

    The deployed bot and the test bot are different bots with different tokens.
    Routine smoke runs should not make the real bot write into a child's chat,
    so the harness prefers `E2E_BOT_TOKEN` when one is configured and falls back
    to the deployed token otherwise.
    """
    overrides: dict[str, str] = {}
    token = _optional("E2E_BOT_TOKEN")
    if token:
        overrides["TOKEN_API_BOT"] = token
    return overrides


def mask(secret: str) -> str:
    """Render a secret safely for logs and admin pages."""
    if not secret:
        return "<unset>"
    if len(secret) <= 10:
        return "***"
    return f"{secret[:6]}...{secret[-4:]}"


@dataclass(frozen=True)
class Settings:
    """Everything the application needs to run."""

    bot_token: str
    redis_url: str
    db_path: Path
    admin_ids: frozenset[int]

    http_proxy_url: str
    log_level: str

    llm_api_key: str
    lmstudio_base_url: str
    lmstudio_model: str
    lmstudio_timeout: float
    openrouter_base_url: str
    openrouter_model: str
    openrouter_timeout: float

    phrase_pool_target: int
    phrase_pool_max: int
    phrase_max_length: int
    phrase_max_emoji: int
    phrase_generate_retries: int

    throttle_messages: int
    throttle_window_seconds: float
    max_input_length: int
    session_idle_timeout_seconds: int

    admin_web_user: str
    admin_web_password: str
    balance_cache_seconds: int

    @classmethod
    def from_env(cls) -> "Settings":
        admin_ids = _ids("ADMIN_IDS")
        return cls(
            bot_token=_require("TOKEN_API_BOT"),
            redis_url=_redis_url(_optional("REDIS", "redis:6379")),
            db_path=Path(_optional("DB_PATH", "/data/numbers.sqlite3")),
            admin_ids=admin_ids,
            http_proxy_url=_optional("HTTP_PROXY_URL"),
            log_level=_optional("LOG_LEVEL", "INFO").upper(),
            llm_api_key=_optional("API_KEY_LLM"),
            lmstudio_base_url=_optional("LMSTUDIO_BASE_URL", "http://<lm-studio-host>:1234/v1"),
            lmstudio_model=_optional("LMSTUDIO_MODEL", "gigachat3.1-10b-a1.8b"),
            lmstudio_timeout=_float("LMSTUDIO_TIMEOUT", 60.0),
            openrouter_base_url=_optional("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            openrouter_model=_optional("OPENROUTER_MODEL", "google/gemma-3-12b-it"),
            openrouter_timeout=_float("OPENROUTER_TIMEOUT", 30.0),
            phrase_pool_target=_int("PHRASE_POOL_TARGET", 10),
            phrase_pool_max=_int("PHRASE_POOL_MAX", 40),
            phrase_max_length=_int("PHRASE_MAX_LENGTH", 160),
            phrase_max_emoji=_int("PHRASE_MAX_EMOJI", 6),
            phrase_generate_retries=_int("PHRASE_GENERATE_RETRIES", 3),
            throttle_messages=_int("THROTTLE_MESSAGES", 5),
            throttle_window_seconds=_float("THROTTLE_WINDOW_SECONDS", 3.0),
            max_input_length=_int("MAX_INPUT_LENGTH", 200),
            session_idle_timeout_seconds=_int("SESSION_IDLE_TIMEOUT_SECONDS", 1800),
            admin_web_user=_optional("ADMIN_WEB_USER", "admin"),
            admin_web_password=_optional("ADMIN_WEB_PASSWORD"),
            balance_cache_seconds=_int("BALANCE_CACHE_SECONDS", 300),
        )

    def describe(self) -> str:
        """A startup log line with every secret masked."""
        return (
            "settings: "
            f"token={mask(self.bot_token)} "
            f"redis={self.redis_url} "
            f"db={self.db_path} "
            f"admins={sorted(self.admin_ids)} "
            f"proxy={self.http_proxy_url or '<none>'} "
            f"llm_key={mask(self.llm_api_key)} "
            f"lmstudio={self.lmstudio_base_url} "
            f"openrouter={self.openrouter_base_url} model={self.openrouter_model} "
            f"log_level={self.log_level}"
        )


@dataclass(frozen=True)
class AdminWebSettings:
    """The subset of configuration the dashboard process needs."""

    db_path: Path
    admin_web_user: str
    admin_web_password: str
    http_proxy_url: str
    llm_api_key: str
    openrouter_base_url: str
    balance_cache_seconds: int
    log_level: str

    @classmethod
    def from_env(cls) -> "AdminWebSettings":
        password = _optional("ADMIN_WEB_PASSWORD")
        if not password:
            raise ConfigError(
                "Required environment variable 'ADMIN_WEB_PASSWORD' is not set — "
                "the dashboard refuses to start without authentication"
            )
        return cls(
            db_path=Path(_optional("DB_PATH", "/data/numbers.sqlite3")),
            admin_web_user=_optional("ADMIN_WEB_USER", "admin"),
            admin_web_password=password,
            http_proxy_url=_optional("HTTP_PROXY_URL"),
            llm_api_key=_optional("API_KEY_LLM"),
            openrouter_base_url=_optional("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            balance_cache_seconds=_int("BALANCE_CACHE_SECONDS", 300),
            log_level=_optional("LOG_LEVEL", "INFO").upper(),
        )

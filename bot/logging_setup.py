"""Logging configuration.

Two sinks. The console keeps `docker logs` useful. A rotating file next to the
database keeps enough history to debug something that happened yesterday, and
lets the dashboard show recent log lines without an ssh session.

Every record carries the Telegram user id when there is one, because the first
question about any misbehaviour is "who was it".
"""

from __future__ import annotations

import logging
import logging.handlers
from contextvars import ContextVar
from pathlib import Path

#: Set by the audit middleware for the duration of one update, so any log line
#: written while handling it is attributable without threading an id through
#: every function signature.
current_user_id: ContextVar[int | None] = ContextVar("current_user_id", default=None)

LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(user)s] %(name)s:%(lineno)d %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

#: Keep roughly a fortnight of chatter at INFO for a bot this size.
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5


class UserContextFilter(logging.Filter):
    """Add the `user` field every formatter in this app expects."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "user"):
            user_id = current_user_id.get()
            record.user = str(user_id) if user_id is not None else "-"
        return True


def log_path(db_path: Path | str, name: str) -> Path:
    """Put logs beside the database, so one volume holds all the state."""
    return Path(db_path).parent / "logs" / name


def setup_logging(level: str, db_path: Path | str | None = None, name: str = "bot.log") -> None:
    """Configure the root logger. Safe to call twice; handlers are replaced."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    context_filter = UserContextFilter()

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.addFilter(context_filter)
    root.addHandler(console)

    if db_path is not None:
        path = log_path(db_path, name)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            file_handler.addFilter(context_filter)
            root.addHandler(file_handler)
        except OSError as exc:
            # A read-only or missing volume must not stop the bot from starting.
            root.warning("file logging disabled: cannot write %s (%s)", path, exc)

    # aiogram and aiohttp are chatty at DEBUG and say little at INFO; keep them
    # one notch quieter than our own code so our lines stay readable.
    for noisy in ("aiogram.event", "aiohttp.access", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def tail(path: Path | str, lines: int = 200) -> list[str]:
    """Read the last `lines` lines of a log file, for the dashboard.

    Reads from the end in blocks rather than loading the whole file, so a log
    that has grown to its rotation limit still renders instantly.
    """
    path = Path(path)
    if not path.exists():
        return []

    block = 8192
    data = b""
    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        while size > 0 and data.count(b"\n") <= lines:
            step = min(block, size)
            size -= step
            handle.seek(size)
            data = handle.read(step) + data

    text = data.decode("utf-8", errors="replace")
    return text.splitlines()[-lines:]
